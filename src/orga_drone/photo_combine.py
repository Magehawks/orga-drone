"""Combine 2..N library photos into one PNG/JPEG (Image Composer #453).

Native oriented sizes, cross-axis centering, optional spacing. Reuses Pillow and
the still-export publish/security path. No grades, thumbs, or source mutation.
"""

from __future__ import annotations

import io
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from orga_drone.db import Database
from orga_drone.export.studio_encoder import (
    ExportCancelled,
    StudioExportError,
    _publish_export_file,
)
from orga_drone.media_files import resolve_media_file

# Discovery #452 / #453 locked limits.
MAX_OUTPUT_PIXELS = 89_478_485  # Pillow Image.MAX_IMAGE_PIXELS default
MAX_EDGE = 32_767
PREVIEW_LONG_EDGE = 1_280
JPEG_QUALITY = 95
FIXED_OVERHEAD_BYTES = 64 * 1024 * 1024
DECODE_SCRATCH_FACTOR = 1.0
ENCODE_SCRATCH_FACTOR = 1.0
PEAK_CAP_BYTES = int(1.5 * 1024 * 1024 * 1024)
RAM_FRACTION = 0.35
MIN_MACHINE_BYTES = 512 * 1024 * 1024

LAYOUTS = frozenset({"horizontal", "vertical"})
BACKGROUNDS = frozenset({"white", "black", "transparent"})
FORMATS = frozenset({"png", "jpeg"})


@dataclass(frozen=True)
class CombineEntrySpec:
    """One list row. ``entry_id`` is the UI identity; media_id may repeat."""

    entry_id: str
    media_id: int


@dataclass(frozen=True)
class CombineSpec:
    entries: tuple[CombineEntrySpec, ...]
    layout: str
    spacing: int
    background: str
    format: str
    revision: int = 1


@dataclass(frozen=True)
class InspectedSource:
    entry_id: str
    media_id: int
    path: Path
    width: int
    height: int
    size_bytes: int
    mtime_ns: int
    filename: str


@dataclass(frozen=True)
class Placement:
    entry_id: str
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class GeometryPlan:
    width: int
    height: int
    placements: tuple[Placement, ...]
    estimated_peak_bytes: int
    constraint: str | None = None


def parse_combine_payload(payload: object) -> CombineSpec:
    """Strict JSON → CombineSpec. Raises StudioExportError on bad input."""
    if not isinstance(payload, dict):
        raise StudioExportError("Invalid combine request.")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise StudioExportError("Add at least one image.")
    entries: list[CombineEntrySpec] = []
    seen_ids: set[str] = set()
    for item in raw_entries:
        if not isinstance(item, dict):
            raise StudioExportError("Each image entry must be an object.")
        entry_id = str(item.get("entry_id") or "").strip()
        media_id = item.get("media_id")
        if not entry_id:
            raise StudioExportError("Each image needs a stable entry id.")
        if entry_id in seen_ids:
            raise StudioExportError("Duplicate entry id in the list.")
        if not isinstance(media_id, int) or media_id < 1:
            raise StudioExportError("Each image needs a valid media id.")
        seen_ids.add(entry_id)
        entries.append(CombineEntrySpec(entry_id=entry_id, media_id=media_id))
    layout = str(payload.get("layout") or "horizontal").strip().lower()
    if layout not in LAYOUTS:
        raise StudioExportError("Choose horizontal or vertical layout.")
    spacing = payload.get("spacing", 0)
    if isinstance(spacing, bool) or not isinstance(spacing, int) or spacing < 0:
        raise StudioExportError("Spacing must be a whole number of pixels (0 or more).")
    background = str(payload.get("background") or "white").strip().lower()
    if background not in BACKGROUNDS:
        raise StudioExportError("Choose white, black, or transparent background.")
    fmt = str(payload.get("format") or "png").strip().lower()
    if fmt in {"jpg", "jpeg"}:
        fmt = "jpeg"
    if fmt not in FORMATS:
        raise StudioExportError("Choose PNG or JPEG.")
    if fmt == "jpeg" and background == "transparent":
        raise StudioExportError("JPEG cannot use a transparent background. Choose white or black.")
    revision = payload.get("revision", 1)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise StudioExportError("Invalid revision.")
    return CombineSpec(
        entries=tuple(entries),
        layout=layout,
        spacing=spacing,
        background=background,
        format=fmt,
        revision=revision,
    )


def require_combine_ready(spec: CombineSpec) -> None:
    if len(spec.entries) < 2:
        raise StudioExportError("Add at least one more image.")


def _oriented_size(img) -> tuple[int, int]:
    """Width/height after EXIF orientation, without keeping a transposed copy."""
    from PIL import ImageOps

    # ImageOps.exif_transpose returns a new image when orientation ≠ 1.
    transposed = ImageOps.exif_transpose(img)
    if transposed is None:
        w, h = img.size
        return int(w), int(h)
    w, h = transposed.size
    if transposed is not img:
        try:
            transposed.close()
        except Exception:
            pass
    return int(w), int(h)


def _header_inspect(path: Path) -> tuple[int, int]:
    from PIL import Image

    from orga_drone.parse import ensure_heif_support

    ensure_heif_support()
    try:
        with Image.open(path) as img:
            # Header size first; orientation may swap axes without full decode.
            try:
                img.load()
            except Exception as exc:  # noqa: BLE001
                raise StudioExportError("Could not read this photo.") from exc
            w, h = _oriented_size(img)
    except StudioExportError:
        raise
    except OSError as exc:
        raise StudioExportError("Could not read this photo.") from exc
    if w < 1 or h < 1:
        raise StudioExportError("Could not read this photo.")
    return w, h


def inspect_sources(db: Database, spec: CombineSpec) -> tuple[InspectedSource, ...]:
    """Resolve and measure every entry. Fail closed on any bad input."""
    require_combine_ready(spec)
    roots = None
    out: list[InspectedSource] = []
    for entry in spec.entries:
        row = db.get_media(entry.media_id)
        if row is None:
            raise StudioExportError("One of the selected photos is missing.")
        if row.kind != "photo":
            raise StudioExportError("Combine works with photos only.")
        path = resolve_media_file(db, row, roots=roots)
        if path is None or not path.is_file():
            raise StudioExportError(
                "One of the selected photos is unavailable. Reconnect the library folder."
            )
        try:
            st = path.stat()
        except OSError as exc:
            raise StudioExportError(
                "One of the selected photos is unavailable. Reconnect the library folder."
            ) from exc
        width, height = _header_inspect(path)
        area = width * height
        if area > MAX_OUTPUT_PIXELS or width > MAX_EDGE or height > MAX_EDGE:
            raise StudioExportError(
                "One source photo is too large to combine. Remove it or use a smaller file."
            )
        out.append(
            InspectedSource(
                entry_id=entry.entry_id,
                media_id=entry.media_id,
                path=path,
                width=width,
                height=height,
                size_bytes=int(st.st_size),
                mtime_ns=int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
                filename=row.filename,
            )
        )
    return tuple(out)


def _checked_sum(values: Sequence[int], *, label: str) -> int:
    total = 0
    for value in values:
        if value < 0:
            raise StudioExportError(f"Invalid {label}.")
        nxt = total + value
        if nxt < total:
            raise StudioExportError(
                "This combination is too large. Remove an image or reduce spacing."
            )
        total = nxt
    return total


def compute_geometry(
    sources: Sequence[InspectedSource],
    *,
    layout: str,
    spacing: int,
    background: str,
    fmt: str,
) -> GeometryPlan:
    n = len(sources)
    if n < 2:
        raise StudioExportError("Add at least one more image.")
    if spacing < 0:
        raise StudioExportError("Spacing must be a whole number of pixels (0 or more).")
    gaps = n - 1
    try:
        gap_total = gaps * spacing
    except OverflowError as exc:
        raise StudioExportError(
            "This combination is too large. Remove an image or reduce spacing."
        ) from exc
    if gap_total < 0:
        raise StudioExportError(
            "This combination is too large. Remove an image or reduce spacing."
        )

    if layout == "horizontal":
        widths = [s.width for s in sources]
        heights = [s.height for s in sources]
        content_w = _checked_sum(widths, label="width")
        width = content_w + gap_total
        height = max(heights)
        if width < content_w:
            raise StudioExportError(
                "This combination is too large. Remove an image or reduce spacing."
            )
        placements: list[Placement] = []
        x = 0
        for i, src in enumerate(sources):
            y = (height - src.height) // 2
            placements.append(
                Placement(entry_id=src.entry_id, x=x, y=y, width=src.width, height=src.height)
            )
            x += src.width
            if i < gaps:
                x += spacing
    elif layout == "vertical":
        widths = [s.width for s in sources]
        heights = [s.height for s in sources]
        content_h = _checked_sum(heights, label="height")
        height = content_h + gap_total
        width = max(widths)
        if height < content_h:
            raise StudioExportError(
                "This combination is too large. Remove an image or reduce spacing."
            )
        placements = []
        y = 0
        for i, src in enumerate(sources):
            x = (width - src.width) // 2
            placements.append(
                Placement(entry_id=src.entry_id, x=x, y=y, width=src.width, height=src.height)
            )
            y += src.height
            if i < gaps:
                y += spacing
    else:
        raise StudioExportError("Choose horizontal or vertical layout.")

    constraint = _admission_constraint(width, height, sources, background=background, fmt=fmt)
    peak = _estimate_peak_bytes(width, height, sources, background=background, fmt=fmt)
    return GeometryPlan(
        width=width,
        height=height,
        placements=tuple(placements),
        estimated_peak_bytes=peak,
        constraint=constraint,
    )


def _bytes_per_pixel(*, background: str, fmt: str) -> int:
    if fmt == "png" and background == "transparent":
        return 4
    return 3 if fmt == "jpeg" or background != "transparent" else 4


def _estimate_peak_bytes(
    width: int,
    height: int,
    sources: Sequence[InspectedSource],
    *,
    background: str,
    fmt: str,
) -> int:
    bpp = _bytes_per_pixel(background=background, fmt=fmt)
    canvas = width * height * (4 if background == "transparent" or fmt == "png" else 3)
    max_src = max((s.width * s.height * 4 for s in sources), default=0)
    peak = (
        canvas
        + max_src
        + int(DECODE_SCRATCH_FACTOR * max_src)
        + int(ENCODE_SCRATCH_FACTOR * canvas)
        + FIXED_OVERHEAD_BYTES
    )
    _ = bpp
    return int(peak)


def _total_ram_bytes() -> int | None:
    """Best-effort physical RAM size (Windows). Other platforms return None."""
    try:
        import ctypes
        import sys

        if sys.platform != "win32":
            return None

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        kernel32 = getattr(ctypes, "windll", None)
        if kernel32 is None:
            return None
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if kernel32.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return int(stat.ullTotalPhys)
    except Exception:
        pass
    return None


def _peak_budget_bytes() -> int:
    total = _total_ram_bytes()
    if total is None:
        return PEAK_CAP_BYTES
    if total < MIN_MACHINE_BYTES:
        return 0
    return min(PEAK_CAP_BYTES, int(total * RAM_FRACTION))


def _admission_constraint(
    width: int,
    height: int,
    sources: Sequence[InspectedSource],
    *,
    background: str,
    fmt: str,
) -> str | None:
    if width < 1 or height < 1:
        return "dimensions"
    if width > MAX_EDGE or height > MAX_EDGE:
        return "edge"
    area = width * height
    if area > MAX_OUTPUT_PIXELS:
        return "area"
    peak = _estimate_peak_bytes(width, height, sources, background=background, fmt=fmt)
    budget = _peak_budget_bytes()
    if budget <= 0 or peak > budget:
        return "memory"
    return None


def refuse_if_unsafe(plan: GeometryPlan) -> None:
    if plan.constraint is None:
        return
    if plan.constraint == "edge":
        raise StudioExportError(
            "This combination is too wide or tall. Remove an image or reduce spacing."
        )
    if plan.constraint == "area":
        raise StudioExportError(
            "This combination has too many pixels. Remove an image or reduce spacing."
        )
    if plan.constraint == "memory":
        raise StudioExportError(
            "This combination needs too much memory. Remove an image or reduce spacing."
        )
    raise StudioExportError(
        "This combination is too large. Remove an image or reduce spacing."
    )


def inspect_combine(db: Database, spec: CombineSpec) -> dict[str, Any]:
    sources = inspect_sources(db, spec)
    plan = compute_geometry(
        sources,
        layout=spec.layout,
        spacing=spec.spacing,
        background=spec.background,
        fmt=spec.format,
    )
    ok = plan.constraint is None
    error = None
    if not ok:
        try:
            refuse_if_unsafe(plan)
        except StudioExportError as exc:
            error = str(exc)
    return {
        "ok": ok,
        "revision": spec.revision,
        "layout": spec.layout,
        "spacing": spec.spacing,
        "background": spec.background,
        "format": spec.format,
        "width": plan.width,
        "height": plan.height,
        "count": len(sources),
        "estimated_peak_bytes": plan.estimated_peak_bytes,
        "constraint": plan.constraint,
        "error": error,
        "entries": [
            {
                "entry_id": s.entry_id,
                "media_id": s.media_id,
                "filename": s.filename,
                "width": s.width,
                "height": s.height,
            }
            for s in sources
        ],
        "placements": [
            {
                "entry_id": p.entry_id,
                "x": p.x,
                "y": p.y,
                "width": p.width,
                "height": p.height,
            }
            for p in plan.placements
        ],
    }


def _bg_rgba(background: str) -> tuple[int, int, int, int]:
    if background == "black":
        return (0, 0, 0, 255)
    if background == "transparent":
        return (0, 0, 0, 0)
    return (255, 255, 255, 255)


def _load_oriented_rgba(path: Path):
    from PIL import Image, ImageOps

    from orga_drone.parse import ensure_heif_support

    ensure_heif_support()
    try:
        img = Image.open(path)
        img.load()
    except OSError as exc:
        raise StudioExportError("Could not read this photo.") from exc
    try:
        oriented = ImageOps.exif_transpose(img) or img
        rgba = oriented.convert("RGBA")
        if oriented is not img and oriented is not rgba:
            try:
                oriented.close()
            except Exception:
                pass
        return rgba
    finally:
        try:
            img.close()
        except Exception:
            pass


def _verify_fingerprint(source: InspectedSource) -> None:
    try:
        st = source.path.stat()
    except OSError as exc:
        raise StudioExportError(
            "One of the selected photos changed or is missing. Refresh the list."
        ) from exc
    size = int(st.st_size)
    mtime = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
    if size != source.size_bytes or mtime != source.mtime_ns:
        raise StudioExportError(
            "One of the selected photos changed or is missing. Refresh the list."
        )


def _compose_rgba(
    sources: Sequence[InspectedSource],
    plan: GeometryPlan,
    *,
    background: str,
    cancel_event: threading.Event | None = None,
):
    from PIL import Image

    refuse_if_unsafe(plan)
    canvas = Image.new("RGBA", (plan.width, plan.height), _bg_rgba(background))
    by_id = {s.entry_id: s for s in sources}
    try:
        for placement in plan.placements:
            if cancel_event is not None and cancel_event.is_set():
                raise ExportCancelled()
            src = by_id[placement.entry_id]
            _verify_fingerprint(src)
            tile = _load_oriented_rgba(src.path)
            try:
                if tile.size != (placement.width, placement.height):
                    raise StudioExportError(
                        "One of the selected photos changed or is missing. Refresh the list."
                    )
                canvas.paste(tile, (placement.x, placement.y), tile)
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
                "JPEG cannot use a transparent background. Choose white or black."
            )
        flat = Image.new("RGB", canvas.size, _bg_rgba(background)[:3])
        try:
            flat.paste(canvas, mask=canvas.split()[3])
            flat.save(dest, format="JPEG", quality=JPEG_QUALITY, optimize=True, subsampling=0)
        finally:
            flat.close()
        return
    # PNG — keep alpha only for transparent background; flatten otherwise.
    if background == "transparent":
        canvas.save(dest, format="PNG", optimize=True)
        return
    rgb = Image.new("RGB", canvas.size, _bg_rgba(background)[:3])
    try:
        rgb.paste(canvas, mask=canvas.split()[3])
        rgb.save(dest, format="PNG", optimize=True)
    finally:
        rgb.close()


def render_preview_png(
    db: Database,
    spec: CombineSpec,
    *,
    cancel_event: threading.Event | None = None,
) -> bytes:
    """Bounded preview PNG (uniform scale of full geometry)."""
    from PIL import Image

    sources = inspect_sources(db, spec)
    plan = compute_geometry(
        sources,
        layout=spec.layout,
        spacing=spec.spacing,
        background=spec.background,
        fmt=spec.format,
    )
    refuse_if_unsafe(plan)
    canvas = _compose_rgba(
        sources, plan, background=spec.background, cancel_event=cancel_event
    )
    try:
        w, h = canvas.size
        long_edge = max(w, h)
        if long_edge > PREVIEW_LONG_EDGE:
            scale = PREVIEW_LONG_EDGE / float(long_edge)
            new_w = max(1, int(round(w * scale)))
            new_h = max(1, int(round(h * scale)))
            preview = canvas.resize((new_w, new_h), Image.Resampling.LANCZOS)
            canvas.close()
            canvas = preview
        buf = io.BytesIO()
        # Preview always PNG so transparent backgrounds stay visible as checkerboard in UI.
        if spec.background != "transparent":
            from PIL import Image as PILImage

            flat = PILImage.new("RGB", canvas.size, _bg_rgba(spec.background)[:3])
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


def export_combine(
    db: Database,
    spec: CombineSpec,
    output_path: Path,
    *,
    cancel_event: threading.Event | None = None,
    on_progress: Any | None = None,
) -> Path:
    """Compose and publish one combine export without overwriting existing files."""
    from orga_drone.studio_export import _snapshot_export_destination

    sources = inspect_sources(db, spec)
    plan = compute_geometry(
        sources,
        layout=spec.layout,
        spacing=spec.spacing,
        background=spec.background,
        fmt=spec.format,
    )
    refuse_if_unsafe(plan)
    suffix = ".png" if spec.format == "png" else ".jpg"
    dest, identities, protected = _snapshot_export_destination(
        db,
        output_path,
        overwrite=False,
        suffix=suffix,
    )
    # Protect every source path as well as the library snapshot.
    source_paths = [str(s.path) for s in sources]
    protected_all = tuple(dict.fromkeys([*protected, *source_paths]))
    tmp_dir = Path(tempfile.mkdtemp(prefix="orga-drone-combine-"))
    partial = tmp_dir / ("out.png" if spec.format == "png" else "out.jpg")
    canvas = None
    try:
        if on_progress is not None:
            on_progress(
                {
                    "phase": "preparing",
                    "clip_index": 1,
                    "clip_total": len(sources),
                    "percent": 5,
                }
            )
        if cancel_event is not None and cancel_event.is_set():
            raise ExportCancelled()
        canvas = _compose_rgba(
            sources, plan, background=spec.background, cancel_event=cancel_event
        )
        if on_progress is not None:
            on_progress(
                {
                    "phase": "rendering",
                    "clip_index": len(sources),
                    "clip_total": len(sources),
                    "percent": 70,
                }
            )
        if cancel_event is not None and cancel_event.is_set():
            raise ExportCancelled()
        _encode_image(canvas, partial, fmt=spec.format, background=spec.background)
        canvas.close()
        canvas = None
        if cancel_event is not None and cancel_event.is_set():
            raise ExportCancelled()
        if not partial.is_file() or partial.stat().st_size <= 0:
            raise StudioExportError("Could not write the combined image.")
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
                    "clip_index": len(sources),
                    "clip_total": len(sources),
                    "percent": 100,
                }
            )
        return result
    finally:
        if canvas is not None:
            try:
                canvas.close()
            except Exception:
                pass
        shutil.rmtree(tmp_dir, ignore_errors=True)


def source_bytes_unchanged(paths: Iterable[Path], snapshots: dict[Path, bytes]) -> bool:
    """Test helper: compare path → original bytes."""
    for path, original in snapshots.items():
        if path.read_bytes() != original:
            return False
    return True
