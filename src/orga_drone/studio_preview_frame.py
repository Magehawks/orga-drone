"""Studio pause/scrub stills that reuse the export grade+LUT filter builders.

When a clip has a non-neutral color look, the WebView2 preview cannot apply
``.cube`` files in CSS. This module renders one JPEG via FFmpeg using the same
``ffmpeg_grade_chain`` and ``ffmpeg_lut_chain`` builders as MP4 export
(ADR 0028). Playback may still approximate without the LUT; pause and scrub
are the honesty gate. Source media is never modified.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.studio_image import ImageAdjust, ffmpeg_grade_chain
from orga_drone.studio_lut import ColorLook, LutMissingError, ffmpeg_lut_chain

logger = logging.getLogger(__name__)

PREVIEW_STILLS_DIR = "preview-stills"
PREVIEW_MAX_EDGE = 720
PREVIEW_QUANTIZE_S = 0.1
PREVIEW_JPEG_Q = 5
PREVIEW_CACHE_MAX_BYTES = 400 * 1024 * 1024
PREVIEW_FFMPEG_TIMEOUT_S = 45.0
PREVIEW_COLD_LATENCY_WARN_S = 1.0

_lock = threading.Lock()
_inflight: dict[str, threading.Event] = {}


@dataclass(frozen=True)
class PreviewFrameRequest:
    """Inputs for one graded+LUT still."""

    media_path: Path
    kind: str
    source_time_s: float
    image: ImageAdjust
    look: ColorLook
    detail: bool = False
    max_edge: int = PREVIEW_MAX_EDGE


class PreviewFrameError(Exception):
    """Still generation failed for a recoverable reason."""

    def __init__(self, message: str, *, code: str = "preview_failed") -> None:
        super().__init__(message)
        self.code = code


def preview_stills_dir(data_dir: Path) -> Path:
    path = data_dir / PREVIEW_STILLS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def look_needs_preview_still(look: ColorLook) -> bool:
    """True when CSS alone cannot show the export look."""
    return not look.is_neutral


def quantize_preview_time(t_s: float, *, step: float = PREVIEW_QUANTIZE_S) -> float:
    if not isinstance(t_s, (int, float)) or t_s != t_s:  # NaN
        return 0.0
    value = max(0.0, float(t_s))
    if step <= 0:
        return value
    return round(value / step) * step


def preview_filter_chain(
    image: ImageAdjust,
    look: ColorLook,
    *,
    data_dir: Path,
    work_dir: Path,
    max_edge: int = PREVIEW_MAX_EDGE,
) -> str:
    """Same grade→LUT order as export; scale for preview; detail omitted."""
    parts: list[str] = []
    grade = ffmpeg_grade_chain(image)
    if grade:
        parts.append(grade)
    if not look.is_neutral:
        lut = ffmpeg_lut_chain(look, data_dir=data_dir, work_dir=work_dir)
        if lut:
            parts.append(lut)
    edge = max(64, min(2160, int(max_edge)))
    # Same scale pattern as export framing: no filter quotes (Windows argv-safe).
    parts.append(
        f"scale={edge}:{edge}:force_original_aspect_ratio=decrease,"
        "format=yuvj420p"
    )
    return ",".join(parts)


def cache_key_for(
    req: PreviewFrameRequest,
    *,
    media_mtime_ns: int,
    media_size: int,
) -> str:
    payload = {
        "path": str(req.media_path.resolve()),
        "mtime_ns": media_mtime_ns,
        "size": media_size,
        "kind": req.kind,
        "t": quantize_preview_time(req.source_time_s),
        "image": req.image.as_dict(),
        "look": req.look.as_dict(),
        "detail": bool(req.detail),
        "edge": int(req.max_edge),
        "v": 1,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _evict_if_needed(cache_dir: Path, *, max_bytes: int = PREVIEW_CACHE_MAX_BYTES) -> None:
    files = [p for p in cache_dir.glob("*.jpg") if p.is_file()]
    total = 0
    stamped: list[tuple[float, int, Path]] = []
    for path in files:
        try:
            st = path.stat()
        except OSError:
            continue
        total += st.st_size
        stamped.append((st.st_mtime, st.st_size, path))
    if total <= max_bytes:
        return
    stamped.sort(key=lambda item: item[0])
    for _mtime, size, path in stamped:
        if total <= max_bytes:
            break
        try:
            path.unlink()
            total -= size
        except OSError:
            continue


def render_preview_frame(
    req: PreviewFrameRequest,
    *,
    data_dir: Path,
    cache_dir: Path | None = None,
) -> Path:
    """Return a JPEG path (cached). Raises PreviewFrameError / LutMissingError."""
    if req.kind not in {"photo", "video"}:
        raise PreviewFrameError("Preview stills are only for photos and videos.", code="unsupported")
    media = req.media_path
    if not media.is_file():
        raise PreviewFrameError("This media file is missing.", code="media_missing")
    try:
        st = media.stat()
    except OSError as exc:
        raise PreviewFrameError("Could not read this media file.", code="media_missing") from exc

    folder = cache_dir if cache_dir is not None else preview_stills_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    key = cache_key_for(req, media_mtime_ns=st.st_mtime_ns, media_size=st.st_size)
    dest = folder / f"{key}.jpg"
    if dest.is_file() and dest.stat().st_size > 0:
        return dest

    with _lock:
        waiter = _inflight.get(key)
        if waiter is None:
            waiter = threading.Event()
            _inflight[key] = waiter
            owner = True
        else:
            owner = False

    if not owner:
        waiter.wait(timeout=PREVIEW_FFMPEG_TIMEOUT_S + 5.0)
        if dest.is_file() and dest.stat().st_size > 0:
            return dest
        raise PreviewFrameError("Could not build the preview still.", code="preview_failed")

    try:
        if dest.is_file() and dest.stat().st_size > 0:
            return dest
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise PreviewFrameError(
                "Install ffmpeg or: pip install imageio-ffmpeg",
                code="ffmpeg_missing",
            )
        work = folder / "work" / key[:16]
        work.mkdir(parents=True, exist_ok=True)
        try:
            vf = preview_filter_chain(
                req.image,
                req.look,
                data_dir=data_dir,
                work_dir=work,
                max_edge=req.max_edge,
            )
        except LutMissingError:
            raise
        except Exception as exc:  # noqa: BLE001 — surface as preview error
            raise PreviewFrameError(str(exc) or "Invalid color look.", code="lut_invalid") from exc

        abs_t = max(0.0, float(req.source_time_s))
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
        if req.kind == "video":
            cmd.extend(["-ss", f"{abs_t:.3f}"])
        cmd.extend(
            [
                "-i",
                str(media),
                "-frames:v",
                "1",
                "-vf",
                vf,
                "-q:v",
                str(PREVIEW_JPEG_Q),
                str(dest),
            ]
        )
        started = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=PREVIEW_FFMPEG_TIMEOUT_S,
                **subprocess_no_window_kwargs(),
            )
        except subprocess.TimeoutExpired as exc:
            raise PreviewFrameError(
                "Building the preview still took too long.",
                code="preview_timeout",
            ) from exc
        except OSError as exc:
            raise PreviewFrameError(
                "Could not run ffmpeg for the preview still.",
                code="preview_failed",
            ) from exc
        elapsed = time.perf_counter() - started
        if elapsed >= PREVIEW_COLD_LATENCY_WARN_S:
            logger.warning(
                "preview still cold latency %.2fs (budget %.1fs) for %s",
                elapsed,
                PREVIEW_COLD_LATENCY_WARN_S,
                media.name,
            )
        if proc.returncode != 0 or not dest.is_file() or dest.stat().st_size <= 0:
            if dest.exists():
                try:
                    dest.unlink()
                except OSError:
                    pass
            detail = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
            raise PreviewFrameError(
                detail or "Could not build the preview still.",
                code="preview_failed",
            )
        _evict_if_needed(folder)
        return dest
    finally:
        with _lock:
            event = _inflight.pop(key, None)
            if event is not None:
                event.set()
