"""Studio Collage still preview and PNG/JPEG export (ADR 0038 / #460).

Composes leaf tiles with the shared layout solver. Does not call or modify
``photo_combine``. Grades apply once on each leaf tile.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from orga_drone.config import settings
from orga_drone.db import Database
from orga_drone.export.studio_encoder import (
    ExportCancelled,
    StudioExportError,
    _publish_export_file,
)
from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_below_normal_kwargs
from orga_drone.media_files import resolve_media_file
from orga_drone.studio_collage import (
    CollageSpecError,
    aspect_size,
    iter_leaves,
    media_source_window,
    normalize_spec,
    resolve_rects,
)
from orga_drone.studio_color_wheels import ColorWheels, color_wheels_from_effect_settings
from orga_drone.studio_hsl import HslAdjust, hsl_adjust_from_effect_settings
from orga_drone.studio_image import ImageAdjust, image_adjust_from_effect_settings
from orga_drone.studio_lut import ColorLook, color_look_from_effect_settings
from orga_drone.studio_preview_frame import (
    PREVIEW_JPEG_Q,
    PreviewFrameError,
    PreviewFrameRequest,
    cache_key_for,
    preview_filter_chain,
    render_preview_frame,
)
from orga_drone.studio_export import _snapshot_export_destination

MAX_OUTPUT_PIXELS = 89_478_485
MAX_EDGE = 8_192
PREVIEW_LONG_EDGE = 1_280
EXPORT_LONG_EDGE = 1_920
JPEG_QUALITY = 95
PLACEHOLDER_RGBA = (28, 32, 36, 255)
MISSING_EXPORT_MEDIA = "A collage source is unavailable. Reconnect or replace it and try again."
UNREADABLE_EXPORT_MEDIA = "A collage source could not be rendered. Check or replace it and try again."

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


@dataclass
class CollageExportFrames:
    """Frame cache owned by one export and removed with its staging directory.

    Optional per-leaf JPEG sequences avoid one FFmpeg process per output frame
    (#487). Sequences live under ``cache_dir`` and are deleted with staging.
    """

    cache_dir: Path
    last_frame_us: dict[tuple[Path, int, int, int, int, int], int] = field(
        default_factory=dict
    )
    # sequence_id -> directory of frame_000000.jpg ...
    sequences: dict[str, Path] = field(default_factory=dict)
    # sequence_id -> {start_s, fps, available, path_key}
    sequence_meta: dict[str, dict[str, Any]] = field(default_factory=dict)



def _export_sequence_id(req: PreviewFrameRequest, *, media_mtime_ns: int, media_size: int) -> str:
    """Stable identity for one graded leaf extract sequence (time-independent)."""
    sample = replace(req, source_time_s=0.0, story_time_s=None)
    return cache_key_for(
        sample,
        media_mtime_ns=media_mtime_ns,
        media_size=media_size,
        data_dir=settings.data_dir,
        source_identity=(0, 0, 0) if req.strict_source else None,
    )


def can_prefetch_export_sequence(req: PreviewFrameRequest) -> bool:
    """True when one sequential FFmpeg extract can replace per-frame seeks."""
    if req.kind != "video":
        return False
    from orga_drone.studio_managed_apply import grade_needs_cpu_materialize

    if req.effect_settings and grade_needs_cpu_materialize(req.effect_settings):
        return False
    return True


def lookup_export_sequence_frame(
    export_frames: CollageExportFrames,
    req: PreviewFrameRequest,
) -> Path | None:
    """Return a prefetched JPEG when the leaf sequence covers ``req``."""
    try:
        st = req.media_path.stat()
    except OSError:
        return None
    seq_id = _export_sequence_id(
        req, media_mtime_ns=st.st_mtime_ns, media_size=st.st_size
    )
    seq_dir = export_frames.sequences.get(seq_id)
    meta = export_frames.sequence_meta.get(seq_id)
    if seq_dir is None or meta is None:
        return None
    available = int(meta.get("available") or 0)
    if available <= 0:
        return None
    fps = float(meta.get("fps") or 30.0)
    start_s = float(meta.get("start_s") or 0.0)
    rel = max(0.0, float(req.source_time_s) - start_s)
    idx = int(round(rel * fps))
    if idx < 0:
        idx = 0
    if idx >= available:
        idx = available - 1
    frame = seq_dir / f"frame_{idx:06d}.jpg"
    if frame.is_file() and frame.stat().st_size > 0:
        return frame
    return None


def prefetch_export_video_sequence(
    export_frames: CollageExportFrames,
    req: PreviewFrameRequest,
    *,
    frame_count: int,
    fps: float,
    start_s: float,
    cancel_event: threading.Event | None = None,
    on_bytes: Any | None = None,
) -> int:
    """Extract ``frame_count`` graded JPEGs with one FFmpeg process.

    Returns frames written. Caller owns disk-space policy via ``on_bytes``.
    """
    _check_cancel(cancel_event)
    if frame_count < 1 or not can_prefetch_export_sequence(req):
        return 0
    media = req.media_path
    try:
        st = media.stat()
    except OSError as exc:
        raise StudioExportError(UNREADABLE_EXPORT_MEDIA) from exc
    seq_id = _export_sequence_id(
        req, media_mtime_ns=st.st_mtime_ns, media_size=st.st_size
    )
    if seq_id in export_frames.sequences:
        return int(export_frames.sequence_meta[seq_id].get("available") or 0)

    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise StudioExportError(
            "Install ffmpeg or: pip install imageio-ffmpeg",
            code="ffmpeg_missing",
        )
    seq_dir = export_frames.cache_dir / "seq" / seq_id[:24]
    if seq_dir.exists():
        shutil.rmtree(seq_dir, ignore_errors=True)
    seq_dir.mkdir(parents=True, exist_ok=True)
    work = export_frames.cache_dir / "seq-work" / seq_id[:16]
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    try:
        _check_cancel(cancel_event)
        try:
            vf_body = preview_filter_chain(
                req.image,
                req.look,
                data_dir=settings.data_dir,
                work_dir=work,
                max_edge=req.max_edge,
                even_dimensions=False,
                saturation=req.saturation,
                hsl=req.hsl,
                color_wheels=req.color_wheels,
                effect_settings=req.effect_settings,
            )
        except Exception as exc:  # noqa: BLE001
            raise StudioExportError(str(exc) or UNREADABLE_EXPORT_MEDIA) from exc
        vf = f"fps={float(fps):.6f}," + vf_body
        pattern = str(seq_dir / "frame_%06d.jpg")
        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{max(0.0, float(start_s)):.6f}",
            "-i",
            str(media),
            "-frames:v",
            str(int(frame_count)),
            "-vf",
            vf,
            "-q:v",
            str(PREVIEW_JPEG_Q),
            "-start_number",
            "0",
            pattern,
        ]
        timeout_s = max(60.0, float(frame_count) * 0.75)
        try:
            result = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=timeout_s,
                **subprocess_below_normal_kwargs(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise StudioExportError(UNREADABLE_EXPORT_MEDIA) from exc
        _check_cancel(cancel_event)
        written = 0
        total_bytes = 0
        for index in range(int(frame_count)):
            frame = seq_dir / f"frame_{index:06d}.jpg"
            if not frame.is_file() or frame.stat().st_size <= 0:
                break
            size = int(frame.stat().st_size)
            if on_bytes is not None:
                on_bytes(size)
            total_bytes += size
            written += 1
        if written <= 0:
            detail = (result.stderr or b"").decode("utf-8", errors="replace").strip()
            raise StudioExportError(detail or UNREADABLE_EXPORT_MEDIA)
        export_frames.sequences[seq_id] = seq_dir
        export_frames.sequence_meta[seq_id] = {
            "start_s": float(start_s),
            "fps": float(fps),
            "available": int(written),
            "bytes": int(total_bytes),
        }
        return written
    finally:
        shutil.rmtree(work, ignore_errors=True)


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
        row = None
        media_id = media.get("media_id")
        if isinstance(media_id, int) and not isinstance(media_id, bool) and media_id > 0:
            row = db.get_media(media_id)
        if row is None:
            identity = str(media.get("identity_key") or "").strip()
            if identity:
                with db.connect() as conn:
                    found = conn.execute(
                        """
                        SELECT m.id
                        FROM media m
                        JOIN media_meta mm ON mm.media_path = m.path
                        WHERE mm.identity_key = ?
                        LIMIT 1
                        """,
                        (identity,),
                    ).fetchone()
                if found is not None:
                    row = db.get_media(int(found["id"]))
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
        return path if path.is_file() else None
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
    from orga_drone.studio_looks import look_id_from_effect_settings
    from orga_drone.studio_managed_apply import grade_is_managed_sdr

    if grade_is_managed_sdr(effect_settings):
        return True
    # Quick Look id alone must still go through the graded still path (e.g. natural
    # is slider-neutral but should stay on the look-aware compose path).
    if look_id_from_effect_settings(effect_settings):
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
        with Image.open(path) as img, ImageOps.exif_transpose(img) as oriented:
            return oriented.convert("RGBA")
    except OSError as exc:
        raise StudioExportError(UNREADABLE_EXPORT_MEDIA) from exc


def _render_graded_or_video_rgba(
    path: Path,
    *,
    kind: str,
    source_time_s: float,
    effect_settings: str | None,
    max_edge: int,
    exact_time: bool = False,
    export_frames: CollageExportFrames | None = None,
    cancel_event: threading.Event | None = None,
):
    from PIL import Image

    _check_cancel(cancel_event)
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
        exact_time=bool(exact_time),
        strict_source=export_frames is not None,
    )
    try:
        if export_frames is not None and kind == "video":
            jpeg = _render_export_video_frame(req, export_frames, cancel_event)
        else:
            jpeg = render_preview_frame(
                req,
                data_dir=settings.data_dir,
                cache_dir=export_frames.cache_dir if export_frames is not None else None,
            )
    except (OSError, PreviewFrameError) as exc:
        _check_cancel(cancel_event)
        raise StudioExportError(str(exc) or "Could not build a collage leaf still.") from exc
    _check_cancel(cancel_event)
    try:
        with Image.open(jpeg) as img:
            return img.convert("RGBA")
    except OSError as exc:
        raise StudioExportError("Could not read collage leaf still.") from exc


def _fit_tile(tile, rect_w: int, rect_h: int, media: dict[str, Any]):
    from PIL import Image

    sw, sh = tile.size
    fit_mode = str(media.get("fit") or "fill").strip().lower()
    win = media_source_window(
        media,
        source_w=sw,
        source_h=sh,
        cell_w=rect_w,
        cell_h=rect_h,
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
        if fit_mode != "fit":
            # Fill/cover: source_window already cropped to cell aspect.
            if cropped.size != (rect_w, rect_h):
                resized = cropped.resize((rect_w, rect_h), Image.Resampling.LANCZOS)
                cropped.close()
                return resized
            return cropped
        # Fit/contain: preserve aspect and letterbox inside the cell.
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
    except Exception:
        cropped.close()
        raise


_video_duration_cache: dict[str, float | None] = {}


def _probe_video_duration_s(path: Path) -> float | None:
    """Best-effort media duration for hold-last-frame clamps."""
    key = str(path)
    if key in _video_duration_cache:
        return _video_duration_cache[key]
    duration: float | None = None
    try:
        from orga_drone.ffmpeg_bin import find_ffprobe, subprocess_no_window_kwargs
        import json as _json
        import subprocess

        ffprobe = find_ffprobe()
        if ffprobe:
            proc = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    str(path),
                ],
                check=False,
                capture_output=True,
                timeout=8,
                **subprocess_no_window_kwargs(),
            )
            if proc.returncode == 0 and proc.stdout:
                data = _json.loads(proc.stdout.decode("utf-8", errors="replace"))
                raw = (data.get("format") or {}).get("duration")
                if raw is not None:
                    duration = max(0.0, float(raw))
    except Exception:
        duration = None
    _video_duration_cache[key] = duration
    return duration


def resolve_leaf_video_duration_s(
    db: Database, media: dict[str, Any] | None
) -> float | None:
    """Best-effort duration for a collage leaf video, or None when unknown."""
    if not isinstance(media, dict):
        return None
    if str(media.get("kind") or "").strip().lower() != "video":
        return None
    if str(media.get("source") or "").strip().lower() == "library":
        duration = _library_media_duration_s(db, media)
        if duration is not None:
            return duration
    path = resolve_leaf_source(db, media)
    if path is None:
        return None
    return _probe_video_duration_s(path)


def _library_media_duration_s(db: Database, media: dict[str, Any]) -> float | None:
    media_id = media.get("media_id")
    row = None
    if isinstance(media_id, int) and not isinstance(media_id, bool) and media_id > 0:
        row = db.get_media(media_id)
    if row is None:
        identity = str(media.get("identity_key") or "").strip()
        if identity:
            with db.connect() as conn:
                found = conn.execute(
                    """
                    SELECT m.id
                    FROM media m
                    JOIN media_meta mm ON mm.media_path = m.path
                    WHERE mm.identity_key = ?
                    LIMIT 1
                    """,
                    (identity,),
                ).fetchone()
            if found is not None:
                row = db.get_media(int(found["id"]))
    if row is None:
        return None
    raw = getattr(row, "duration_s", None)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _clamp_video_source_time(
    db: Database,
    media: dict[str, Any],
    path: Path,
    source_time: float,
) -> float:
    """Hold the last decodable frame when collage time outruns the leaf video."""
    duration = None
    if media.get("source") == "library":
        duration = _library_media_duration_s(db, media)
    if duration is None:
        duration = _probe_video_duration_s(path)
    if duration is None or duration <= 0:
        return max(0.0, float(source_time))
    # Keep a small epsilon before EOF so ffmpeg -ss still returns a frame.
    hold_at = max(0.0, float(duration) - 0.05)
    return min(max(0.0, float(source_time)), hold_at)


def _render_export_video_frame(
    req: PreviewFrameRequest,
    export_frames: CollageExportFrames,
    cancel_event: threading.Event | None,
) -> Path:
    path = req.media_path
    stat = path.stat()
    key = (path, stat.st_mtime_ns, stat.st_size, stat.st_dev, stat.st_ino, stat.st_ctime_ns)
    last_us = export_frames.last_frame_us.get(key)
    if last_us is not None:
        req = replace(req, source_time_s=min(req.source_time_s, last_us / 1_000_000))
    cached = lookup_export_sequence_frame(export_frames, req)
    if cached is not None:
        return cached
    try:
        return render_preview_frame(
            req,
            data_dir=settings.data_dir,
            cache_dir=export_frames.cache_dir,
            allow_eviction=False,
        )
    except PreviewFrameError as exc:
        if exc.code != "video_eof" or last_us is not None:
            raise
        _check_cancel(cancel_event)
        last_us = _last_video_frame_us(path)
        _check_cancel(cancel_event)
        if last_us >= round(req.source_time_s * 1_000_000):
            raise
        jpeg = render_preview_frame(
            replace(req, source_time_s=last_us / 1_000_000),
            data_dir=settings.data_dir,
            cache_dir=export_frames.cache_dir,
        )
        export_frames.last_frame_us[key] = last_us
        return jpeg


def _last_video_frame_us(path: Path) -> int:
    """Get a decoded frame timestamp, independent of container/audio duration."""
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise StudioExportError(UNREADABLE_EXPORT_MEDIA)
    cmd = [
        ffmpeg, "-hide_banner", "-nostats", "-v", "info",
        "-xerror", "-err_detect", "explode", "-i", str(path),
        "-map", "0:V:0", "-vf", "showinfo=checksum=0", "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=30, check=False, **subprocess_below_normal_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StudioExportError(UNREADABLE_EXPORT_MEDIA) from exc
    base = re.search(rb"\[Parsed_showinfo_[^\]]+\] config in time_base: (\d+)/(\d+)", result.stderr)
    pts = max(
        (int(match[1]) for match in re.finditer(
            rb"\[Parsed_showinfo_[^\]]+\]\s+n:\s*\d+\s+pts:\s*(-?\d+)", result.stderr
        )),
        default=None,
    )
    if result.returncode or base is None or pts is None:
        raise StudioExportError(UNREADABLE_EXPORT_MEDIA)
    return max(0, pts * int(base[1]) * 1_000_000 // int(base[2]))


def render_collage_leaf_source_preview(
    db: Database,
    spec: dict[str, Any],
    leaf_id: str,
    *,
    t_s: float = 0.0,
    max_edge: int = PREVIEW_LONG_EDGE,
) -> Path:
    """Full-source graded JPEG for one leaf (no cell crop).

    Used by the framing dialog so Looks / HSL / LUT show on the photo while the
    orange viewport still tracks the uncropped source aspect.
    """
    normalized = normalize_spec(spec)
    leaf = next(
        (node for node in iter_leaves(normalized["root"]) if str(node.get("id")) == str(leaf_id)),
        None,
    )
    if leaf is None:
        raise StudioExportError("Collage cell not found.")
    media = leaf.get("media")
    if not isinstance(media, dict):
        raise StudioExportError("Collage cell has no media.")
    path = resolve_leaf_source(db, media)
    if path is None or not path.is_file():
        raise StudioExportError("Collage media missing.")

    kind = str(media.get("kind") or "photo").strip().lower()
    if kind not in {"photo", "video"}:
        kind = "photo" if path.suffix.lower() in PHOTO_SUFFIXES else "video"

    effect_settings = _grade_payload(media)
    start_offset = float(media.get("start_offset_s") or 0.0)
    source_time = start_offset + max(0.0, float(t_s))
    if kind == "video":
        source_time = _clamp_video_source_time(db, media, path, source_time)

    image = (
        image_adjust_from_effect_settings(effect_settings)
        if effect_settings
        else ImageAdjust()
    )
    look = (
        color_look_from_effect_settings(effect_settings) if effect_settings else ColorLook()
    )
    hsl = hsl_adjust_from_effect_settings(effect_settings) if effect_settings else HslAdjust()
    wheels = (
        color_wheels_from_effect_settings(effect_settings)
        if effect_settings
        else ColorWheels()
    )
    from orga_drone.studio_managed_apply import grade_is_managed_sdr

    managed = bool(effect_settings and grade_is_managed_sdr(effect_settings))
    req = PreviewFrameRequest(
        media_path=path,
        kind=kind,
        source_time_s=max(0.0, float(source_time)),
        image=image,
        look=look,
        hsl=hsl,
        color_wheels=wheels,
        max_edge=max(64, int(max_edge)),
        effect_settings=effect_settings if managed else None,
    )
    try:
        return render_preview_frame(req, data_dir=settings.data_dir)
    except PreviewFrameError as exc:
        raise StudioExportError(str(exc) or "Could not build a collage leaf still.") from exc


def _leaf_rgba(
    db: Database,
    leaf: dict[str, Any],
    rect_w: int,
    rect_h: int,
    *,
    t_s: float,
    long_edge: int,
    export_frames: CollageExportFrames | None,
    exact_time: bool = False,
    cancel_event: threading.Event | None = None,
):
    from PIL import Image

    _check_cancel(cancel_event)
    media = leaf.get("media")
    if not isinstance(media, dict):
        return Image.new("RGBA", (rect_w, rect_h), PLACEHOLDER_RGBA)
    path = resolve_leaf_source(db, media)
    if path is None:
        if export_frames is not None:
            raise StudioExportError(MISSING_EXPORT_MEDIA)
        return Image.new("RGBA", (rect_w, rect_h), PLACEHOLDER_RGBA)

    kind = str(media.get("kind") or "photo").strip().lower()
    if kind not in {"photo", "video"}:
        kind = "photo" if path.suffix.lower() in PHOTO_SUFFIXES else "video"

    effect_settings = _grade_payload(media)
    start_offset = float(media.get("start_offset_s") or 0.0)
    source_time = start_offset + max(0.0, float(t_s))
    if kind == "video" and export_frames is None:
        source_time = _clamp_video_source_time(db, media, path, source_time)
    needs_preview = kind == "video" or _grade_needs_still(effect_settings)

    if needs_preview:
        try:
            tile = _render_graded_or_video_rgba(
                path,
                kind=kind,
                source_time_s=source_time,
                effect_settings=effect_settings,
                max_edge=max(long_edge, max(rect_w, rect_h)),
                exact_time=exact_time or (export_frames is not None and kind == "video"),
                export_frames=export_frames,
                cancel_event=cancel_event,
            )
        except StudioExportError as exc:
            _check_cancel(cancel_event)
            if export_frames is not None:
                raise StudioExportError(UNREADABLE_EXPORT_MEDIA) from exc
            if kind != "video" or source_time <= 0:
                return Image.new("RGBA", (rect_w, rect_h), PLACEHOLDER_RGBA)
            # Last-resort hold: retry near the start rather than aborting the collage.
            try:
                tile = _render_graded_or_video_rgba(
                    path,
                    kind=kind,
                    source_time_s=0.0,
                    effect_settings=effect_settings,
                    max_edge=max(long_edge, max(rect_w, rect_h)),
                    exact_time=exact_time,
                    cancel_event=cancel_event,
                )
            except StudioExportError:
                _check_cancel(cancel_event)
                return Image.new("RGBA", (rect_w, rect_h), PLACEHOLDER_RGBA)
        # Preview-frame grades through JPEG and loses photo alpha. Restore the
        # source alpha channel so transparent PNGs stay transparent after grade.
        if kind == "photo":
            source = _load_oriented_rgba(path)
            try:
                if source.size != tile.size:
                    from PIL import Image as PILImage

                    alpha = source.split()[3].resize(tile.size, PILImage.Resampling.LANCZOS)
                else:
                    alpha = source.split()[3]
                try:
                    tile.putalpha(alpha)
                finally:
                    alpha.close()
            finally:
                source.close()
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
    exact_time: bool = False,
    export_frames: CollageExportFrames | None = None,
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
                export_frames=export_frames,
                exact_time=exact_time,
                cancel_event=cancel_event,
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


def _background_has_alpha(background: str) -> bool:
    text = (background or "").strip().lower()
    if text == "transparent":
        return True
    rgba = _parse_bg_rgba(text)
    return rgba[3] < 255


def _encode_image(canvas, dest: Path, *, fmt: str, background: str) -> None:
    from PIL import Image

    if fmt == "jpeg":
        if background == "transparent" or _background_has_alpha(background):
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
    # PNG — keep alpha for transparent / RGBA hex backgrounds.
    if _background_has_alpha(background):
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
        if _background_has_alpha(background):
            canvas.save(buf, format="PNG", optimize=True)
        else:
            flat = Image.new("RGB", canvas.size, _parse_bg_rgba(background)[:3])
            try:
                flat.paste(canvas, mask=canvas.split()[3])
                flat.save(buf, format="PNG", optimize=True)
            finally:
                flat.close()
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
    if format_name == "jpeg" and _background_has_alpha(normalized["background"]):
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

    tmp_dir = Path(tempfile.mkdtemp(prefix=".orga-drone-collage-", dir=dest.parent))
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
            export_frames=CollageExportFrames(tmp_dir / "frames"),
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
            require_atomic=True,
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
        if format_name == "jpeg" and _background_has_alpha(normalized["background"]):
            raise StudioExportError(
                "JPEG cannot use a transparent background. Choose a solid color."
            )
        rects = resolve_rects(normalized, width, height)
        leaves = []
        for leaf in iter_leaves(normalized["root"]):
            media = leaf.get("media")
            path = resolve_leaf_source(db, media if isinstance(media, dict) else None)
            if isinstance(media, dict) and path is None:
                raise StudioExportError(MISSING_EXPORT_MEDIA)
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
