"""Studio Collage still preview and PNG/JPEG export (ADR 0038 / #460).

Composes leaf tiles with the shared layout solver. Does not call or modify
``photo_combine``. Grades apply once on each leaf tile.
"""

from __future__ import annotations

import asyncio
import io
import json
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from orga_drone.db import Database
from orga_drone.export.studio_encoder import (
    ExportCancelled,
    StudioExportError,
    _publish_export_file,
)
from orga_drone.media_files import resolve_media_file
from orga_drone.studio_collage import (
    CollageSpecError,
    aspect_size,
    iter_leaves,
    normalize_spec,
    resolve_rects,
    source_window,
)
from orga_drone.studio_color_wheels import ColorWheels, color_wheels_from_effect_settings
from orga_drone.studio_hsl import HslAdjust, hsl_adjust_from_effect_settings
from orga_drone.studio_image import ImageAdjust, image_adjust_from_effect_settings
from orga_drone.studio_lut import ColorLook, color_look_from_effect_settings
from orga_drone.studio_preview_frame import (
    PreviewFrameError,
    PreviewFrameRequest,
    render_preview_frame,
)
from orga_drone.studio_export import _snapshot_export_destination

MAX_OUTPUT_PIXELS = 89_478_485
MAX_EDGE = 8_192
PREVIEW_LONG_EDGE = 1_280
EXPORT_LONG_EDGE = 1_920
JPEG_QUALITY = 95
PLACEHOLDER_RGBA = (28, 32, 36, 255)

PHOTO_SUFFIXES = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".heic", ".heif", ".dng"}
)
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm"})
FORMATS = frozenset({"png", "jpeg"})


class CollageStillPreviewCoordinator:
    """Serialize collage preview composes; newer requests cancel older ones."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self._seq = 0
        self._cancel: threading.Event | None = None

    def claim(self) -> tuple[int, threading.Event]:
        self._seq += 1
        if self._cancel is not None:
            self._cancel.set()
        cancel = threading.Event()
        self._cancel = cancel
        return self._seq, cancel

    def is_current(self, seq: int) -> bool:
        return seq == self._seq

    def release(self, cancel: threading.Event) -> None:
        if self._cancel is cancel:
            self._cancel = None


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ExportCancelled()


def _parse_bg_rgba(background: str) -> tuple[int, int, int, int]:
    text = (background or "").strip().lower()
    if text == "transparent":
        return (0, 0, 0, 0)
    if text.startswith("#") and len(text) in {7, 9}:
        r = int(text[1:3], 16)
        g = int(text[3:5], 16)
        b = int(text[5:7], 16)
        a = int(text[7:9], 16) if len(text) == 9 else 255
        return (r, g, b, a)
    return (10, 12, 14, 255)


def refuse_canvas(width: int, height: int) -> None:
    w = max(0, int(width))
    h = max(0, int(height))
    if w > MAX_EDGE or h > MAX_EDGE:
        raise StudioExportError(
            "This collage is too wide or tall. Reduce the export size or simplify the layout."
        )
    if w * h > MAX_OUTPUT_PIXELS:
        raise StudioExportError(
            "This collage has too many pixels. Reduce the export size or simplify the layout."
        )


def normalize_still_format(raw: Any) -> str:
    text = str(raw or "png").strip().lower()
    if text in {"jpg", "jpeg"}:
        return "jpeg"
    if text == "png":
        return "png"
    raise StudioExportError("Export format must be PNG or JPEG.")


def resolve_leaf_source(db: Database, media: dict[str, Any] | None) -> Path | None:
    """Resolve a leaf media path or return None when missing/unavailable."""
    if not isinstance(media, dict):
        return None
    source = str(media.get("source") or "").strip().lower()
    kind = str(media.get("kind") or "").strip().lower()
    if source == "library":
        media_id = media.get("media_id")
        if not isinstance(media_id, int) or isinstance(media_id, bool) or media_id <= 0:
            return None
        row = db.get_media(media_id)
        if row is None:
            return None
        try:
            path = resolve_media_file(db, row)
        except Exception:
            return None
        if path is None or not path.is_file():
            return None
        return path
    if source == "external":
        raw = str(media.get("path") or "").strip()
        if not raw:
            return None
        try:
            path = Path(raw).expanduser().resolve(strict=True)
        except OSError:
            return None
        suffix = path.suffix.lower()
        if kind == "photo" and suffix not in PHOTO_SUFFIXES:
            return None
        if kind == "video" and suffix not in VIDEO_SUFFIXES:
            return None
        if kind not in {"photo", "video"}:
            if suffix not in PHOTO_SUFFIXES | VIDEO_SUFFIXES:
                return None
        return path
    return None


def _grade_payload(media: dict[str, Any]) -> str | None:
    grade = media.get("grade")
    if not isinstance(grade, dict) or not grade:
        return None
    try:
        return json.dumps(grade, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        return None


def _grade_needs_still(effect_settings: str | None) -> bool:
    if not effect_settings:
        return False
    from orga_drone.studio_managed_apply import grade_is_managed_sdr

    if grade_is_managed_sdr(effect_settings):
        return True
    image = image_adjust_from_effect_settings(effect_settings)
    look = color_look_from_effect_settings(effect_settings)
    hsl = hsl_adjust_from_effect_settings(effect_settings)
    wheels = color_wheels_from_effect_settings(effect_settings)
    if not image.is_neutral:
        return True
    if look.creative_lut or (look.conversion_lut and look.conversion_confirmed):
        return True
    if not hsl.is_neutral or not wheels.is_neutral:
        return True
    return False


def _load_oriented_rgba(path: Path):
    from PIL import Image, ImageOps

    from orga_drone.parse import ensure_heif_support

    ensure_heif_support()
    try:
        img = Image.open(path)
        img.load()
    except OSError as exc:
        raise StudioExportError("Could not read collage media.") from exc
    try:
        oriented = ImageOps.exif_transpose(img) or img
        return oriented.convert("RGBA")
    finally:
        try:
            img.close()
        except Exception:
            pass


def _render_graded_or_video_rgba(
    path: Path,
    *,
    kind: str,
    source_time_s: float,
    effect_settings: str | None,
    max_edge: int,
):
    from PIL import Image

    image = (
        image_adjust_from_effect_settings(effect_settings)
        if effect_settings
        else ImageAdjust()
    )
    look = (
        color_look_from_effect_settings(effect_settings)
        if effect_settings
        else ColorLook()
    )
    hsl = (
        hsl_adjust_from_effect_settings(effect_settings)
        if effect_settings
        else HslAdjust()
    )
    wheels = (
        color_wheels_from_effect_settings(effect_settings)
        if effect_settings
        else ColorWheels()
    )
    from orga_drone.studio_managed_apply import grade_is_managed_sdr

    from orga_drone.config import settings

    managed = bool(effect_settings and grade_is_managed_sdr(effect_settings))
    req = PreviewFrameRequest(
        media_path=path,
        kind=kind,
        source_time_s=max(0.0, float(source_time_s)),
        image=image,
        look=look,
        hsl=hsl,
        color_wheels=wheels,
        max_edge=max(64, int(max_edge)),
        effect_settings=effect_settings if managed else None,
    )
    try:
        jpeg = render_preview_frame(req, data_dir=settings.data_dir)
    except PreviewFrameError as exc:
        raise StudioExportError(str(exc) or "Could not build a collage leaf still.") from exc
    try:
        img = Image.open(jpeg)
        img.load()
        return img.convert("RGBA")
    except OSError as exc:
        raise StudioExportError("Could not read collage leaf still.") from exc


def _fit_tile(tile, rect_w: int, rect_h: int, media: dict[str, Any]):
    from PIL import Image

    sw, sh = tile.size
    fit_mode = str(media.get("fit") or "fill").strip().lower()
    zoom_raw = media.get("zoom")
    pan_x_raw = media.get("pan_x")
    pan_y_raw = media.get("pan_y")
    zoom = float(zoom_raw if zoom_raw is not None else 1.0)
    pan_x = float(pan_x_raw if pan_x_raw is not None else 0.5)
    pan_y = float(pan_y_raw if pan_y_raw is not None else 0.5)
    win = source_window(
        source_w=sw,
        source_h=sh,
        cell_w=rect_w,
        cell_h=rect_h,
        fit=fit_mode,
        zoom=zoom,
        pan_x=pan_x,
        pan_y=pan_y,
    )
    left = int(round(win.x * sw))
    top = int(round(win.y * sh))
    right = int(round((win.x + win.w) * sw))
    bottom = int(round((win.y + win.h) * sh))
    left = max(0, min(sw - 1, left))
    top = max(0, min(sh - 1, top))
    right = max(left + 1, min(sw, right))
    bottom = max(top + 1, min(sh, bottom))
    cropped = tile.crop((left, top, right, bottom))
    try:
        if fit_mode == "fit":
            # Contain: preserve aspect and letterbox inside the cell.
            scale = min(rect_w / cropped.width, rect_h / cropped.height)
            new_w = max(1, int(round(cropped.width * scale)))
            new_h = max(1, int(round(cropped.height * scale)))
            resized = cropped.resize((new_w, new_h), Image.Resampling.LANCZOS)
            cropped.close()
            cell = Image.new("RGBA", (rect_w, rect_h), (0, 0, 0, 0))
            try:
                ox = (rect_w - new_w) // 2
                oy = (rect_h - new_h) // 2
                # Paste RGBA without a mask so source alpha is not multiplied twice.
                cell.paste(resized, (ox, oy))
            finally:
                resized.close()
            return cell
        if cropped.size != (rect_w, rect_h):
            resized = cropped.resize((rect_w, rect_h), Image.Resampling.LANCZOS)
            cropped.close()
            return resized
        return cropped
    except Exception:
        cropped.close()
        raise


def _leaf_rgba(
    db: Database,
    leaf: dict[str, Any],
    rect_w: int,
    rect_h: int,
    *,
    t_s: float,
    long_edge: int,
):
    from PIL import Image

    media = leaf.get("media")
    path = resolve_leaf_source(db, media if isinstance(media, dict) else None)
    if path is None or not isinstance(media, dict):
        return Image.new("RGBA", (rect_w, rect_h), PLACEHOLDER_RGBA)

    kind = str(media.get("kind") or "photo").strip().lower()
    if kind not in {"photo", "video"}:
        kind = "photo" if path.suffix.lower() in PHOTO_SUFFIXES else "video"

    effect_settings = _grade_payload(media)
    start_offset = float(media.get("start_offset_s") or 0.0)
    source_time = start_offset + max(0.0, float(t_s))
    needs_preview = kind == "video" or _grade_needs_still(effect_settings)

    if needs_preview:
        tile = _render_graded_or_video_rgba(
            path,
            kind=kind,
            source_time_s=source_time,
            effect_settings=effect_settings,
            max_edge=max(long_edge, max(rect_w, rect_h)),
        )
    else:
        tile = _load_oriented_rgba(path)
    try:
        return _fit_tile(tile, rect_w, rect_h, media)
    finally:
        tile.close()


def compose_collage_rgba(
    db: Database,
    spec: dict[str, Any],
    *,
    long_edge: int = EXPORT_LONG_EDGE,
    t_s: float = 0.0,
    cancel_event: threading.Event | None = None,
):
    """Compose one RGBA collage canvas from the layout SoT."""
    from PIL import Image

    normalized = normalize_spec(spec)
    width, height = aspect_size(normalized["aspect"], long_edge=int(long_edge))
    refuse_canvas(width, height)
    rects = resolve_rects(normalized, width, height)
    canvas = Image.new("RGBA", (width, height), _parse_bg_rgba(normalized["background"]))
    try:
        for leaf in iter_leaves(normalized["root"]):
            _check_cancel(cancel_event)
            leaf_id = str(leaf["id"])
            rect = rects.get(leaf_id)
            if rect is None:
                continue
            tile = _leaf_rgba(
                db,
                leaf,
                rect.w,
                rect.h,
                t_s=t_s,
                long_edge=long_edge,
            )
            try:
                box = (rect.x, rect.y, rect.x + rect.w, rect.y + rect.h)
                region = canvas.crop(box)
                blended = None
                try:
                    blended = Image.alpha_composite(region, tile)
                    canvas.paste(blended, box[:2])
                finally:
                    region.close()
                    if blended is not None:
                        blended.close()
            finally:
                tile.close()
        return canvas
    except Exception:
        canvas.close()
        raise


def _encode_image(canvas, dest: Path, *, fmt: str, background: str) -> None:
    from PIL import Image

    if fmt == "jpeg":
        if background == "transparent":
            raise StudioExportError(
                "JPEG cannot use a transparent background. Choose a solid color."
            )
        rgb = _parse_bg_rgba(background)[:3]
        flat = Image.new("RGB", canvas.size, rgb)
        try:
            flat.paste(canvas, mask=canvas.split()[3])
            flat.save(
                dest,
                format="JPEG",
                quality=JPEG_QUALITY,
                optimize=True,
                subsampling=0,
            )
        finally:
            flat.close()
        return
    if background == "transparent":
        canvas.save(dest, format="PNG", optimize=True)
        return
    rgb = _parse_bg_rgba(background)[:3]
    flat = Image.new("RGB", canvas.size, rgb)
    try:
        flat.paste(canvas, mask=canvas.split()[3])
        flat.save(dest, format="PNG", optimize=True)
    finally:
        flat.close()


def render_collage_preview_png(
    db: Database,
    spec: dict[str, Any],
    *,
    long_edge: int = PREVIEW_LONG_EDGE,
    t_s: float = 0.0,
    cancel_event: threading.Event | None = None,
) -> bytes:
    """Bounded PNG preview of the collage (always PNG for UI honesty)."""
    from PIL import Image

    canvas = compose_collage_rgba(
        db,
        spec,
        long_edge=long_edge,
        t_s=t_s,
        cancel_event=cancel_event,
    )
    try:
        _check_cancel(cancel_event)
        buf = io.BytesIO()
        background = normalize_spec(spec)["background"]
        if background != "transparent":
            flat = Image.new("RGB", canvas.size, _parse_bg_rgba(background)[:3])
            try:
                flat.paste(canvas, mask=canvas.split()[3])
                flat.save(buf, format="PNG", optimize=True)
            finally:
                flat.close()
        else:
            canvas.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    finally:
        canvas.close()


def export_collage_still(
    db: Database,
    spec: dict[str, Any],
    output_path: Path,
    *,
    fmt: str = "png",
    long_edge: int = EXPORT_LONG_EDGE,
    t_s: float = 0.0,
    cancel_event: threading.Event | None = None,
    on_progress: Any | None = None,
) -> Path:
    """Compose and publish one collage still without overwriting sources."""
    format_name = normalize_still_format(fmt)
    normalized = normalize_spec(spec)
    if format_name == "jpeg" and normalized["background"] == "transparent":
        raise StudioExportError(
            "JPEG cannot use a transparent background. Choose a solid color."
        )
    refuse_canvas(*aspect_size(normalized["aspect"], long_edge=int(long_edge)))

    suffix = ".png" if format_name == "png" else ".jpg"
    dest, identities, protected = _snapshot_export_destination(
        db,
        output_path,
        overwrite=False,
        suffix=suffix,
    )
    source_paths: list[str] = []
    for leaf in iter_leaves(normalized["root"]):
        path = resolve_leaf_source(db, leaf.get("media"))
        if path is not None:
            source_paths.append(str(path))
    protected_all = tuple(dict.fromkeys([*protected, *source_paths]))

    tmp_dir = Path(tempfile.mkdtemp(prefix="orga-drone-collage-still-"))
    partial = tmp_dir / ("out.png" if format_name == "png" else "out.jpg")
    canvas = None
    try:
        if on_progress is not None:
            on_progress(
                {
                    "phase": "preparing",
                    "clip_index": 1,
                    "clip_total": max(1, len(iter_leaves(normalized["root"]))),
                    "percent": 5,
                }
            )
        _check_cancel(cancel_event)
        canvas = compose_collage_rgba(
            db,
            normalized,
            long_edge=long_edge,
            t_s=t_s,
            cancel_event=cancel_event,
        )
        if on_progress is not None:
            on_progress(
                {
                    "phase": "rendering",
                    "clip_index": len(iter_leaves(normalized["root"])),
                    "clip_total": max(1, len(iter_leaves(normalized["root"]))),
                    "percent": 70,
                }
            )
        _check_cancel(cancel_event)
        _encode_image(
            canvas,
            partial,
            fmt=format_name,
            background=normalized["background"],
        )
        canvas.close()
        canvas = None
        _check_cancel(cancel_event)
        if not partial.is_file() or partial.stat().st_size <= 0:
            raise StudioExportError("Could not write the collage image.")
        result = _publish_export_file(
            partial,
            dest,
            protected=protected_all,
            protected_identities=identities,
        )
        if on_progress is not None:
            on_progress(
                {
                    "phase": "done",
                    "clip_index": len(iter_leaves(normalized["root"])),
                    "clip_total": max(1, len(iter_leaves(normalized["root"]))),
                    "percent": 100,
                }
            )
        return result
    finally:
        if canvas is not None:
            canvas.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)


def inspect_collage_still(
    db: Database,
    spec: dict[str, Any],
    *,
    long_edge: int = EXPORT_LONG_EDGE,
    fmt: str = "png",
) -> dict[str, Any]:
    """Preflight dimensions and leaf availability for still export."""
    try:
        format_name = normalize_still_format(fmt)
        normalized = normalize_spec(spec)
        width, height = aspect_size(normalized["aspect"], long_edge=int(long_edge))
        refuse_canvas(width, height)
        if format_name == "jpeg" and normalized["background"] == "transparent":
            raise StudioExportError(
                "JPEG cannot use a transparent background. Choose a solid color."
            )
        rects = resolve_rects(normalized, width, height)
        leaves = []
        for leaf in iter_leaves(normalized["root"]):
            media = leaf.get("media")
            path = resolve_leaf_source(db, media if isinstance(media, dict) else None)
            leaves.append(
                {
                    "leaf_id": leaf["id"],
                    "has_media": isinstance(media, dict),
                    "available": path is not None,
                    "rect": {
                        "x": rects[leaf["id"]].x,
                        "y": rects[leaf["id"]].y,
                        "w": rects[leaf["id"]].w,
                        "h": rects[leaf["id"]].h,
                    },
                }
            )
        return {
            "ok": True,
            "width": width,
            "height": height,
            "format": format_name,
            "background": normalized["background"],
            "leaf_count": len(leaves),
            "leaves": leaves,
            "error": None,
        }
    except (CollageSpecError, StudioExportError) as exc:
        return {
            "ok": False,
            "width": None,
            "height": None,
            "format": None,
            "background": None,
            "leaf_count": 0,
            "leaves": [],
            "error": str(exc),
        }
