"""Single-clip Studio LUT playback proxy (Issue #222).

Renders one selected video clip to a local 720p H.264 file using the same
``ffmpeg_grade_chain`` and ``ffmpeg_lut_chain`` builders as Studio export and
pause/scrub stills. The proxy is an internal artifact: it lives under the
application data directory, never beside the source, and is not connected to the
Studio player yet. Source media is never modified.

This is not a cache manager, job queue, or stale-proxy guard (Issue #224). It
only writes one deterministic file and removes its temporary work directory on
success or failure.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.studio_image import ImageAdjust, ffmpeg_grade_chain
from orga_drone.studio_lut import (
    ColorLook,
    LutMissingError,
    ffmpeg_lut_chain,
    require_lut_asset,
)
from orga_drone.studio_preview_frame import look_needs_preview_still

logger = logging.getLogger(__name__)

PLAYBACK_PROXIES_DIR = "playback-proxies"
PROXY_MAX_WIDTH = 1280
PROXY_MAX_HEIGHT = 720
PROXY_FPS = 30
PROXY_CRF = 20
PROXY_PRESET = "veryfast"
PROXY_GOP_FRAMES = 30
PROXY_FFMPEG_TIMEOUT_S = 180.0
PROXY_VERSION = 1


@dataclass(frozen=True)
class PlaybackProxyRequest:
    """Inputs for one static-LUT single-clip playback proxy."""

    media_path: Path
    source_start_s: float = 0.0
    source_end_s: float | None = None
    image: ImageAdjust = field(default_factory=ImageAdjust)
    look: ColorLook = field(default_factory=ColorLook)
    max_width: int = PROXY_MAX_WIDTH
    max_height: int = PROXY_MAX_HEIGHT
    saturation: float = 1.0


class PlaybackProxyError(Exception):
    """Proxy generation failed for a recoverable reason."""

    def __init__(self, message: str, *, code: str = "proxy_failed") -> None:
        super().__init__(message)
        self.code = code


def playback_proxies_dir(data_dir: Path) -> Path:
    path = data_dir / PLAYBACK_PROXIES_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def proxy_filter_chain(
    req: PlaybackProxyRequest,
    *,
    data_dir: Path,
    work_dir: Path,
    max_width: int = PROXY_MAX_WIDTH,
    max_height: int = PROXY_MAX_HEIGHT,
    saturation: float = 1.0,
) -> str:
    """Export grade → LUT order, then a 720p CFR H.264 output frame."""
    parts: list[str] = []
    grade = ffmpeg_grade_chain(req.image)
    if grade:
        parts.append(grade)
    if not req.look.is_neutral:
        lut = ffmpeg_lut_chain(req.look, data_dir=data_dir, work_dir=work_dir)
        if lut:
            parts.append(lut)
    if saturation != 1.0:
        parts.append(f"eq=saturation={max(0.0, min(1.0, saturation)):.6f}")
    edge_w = max(64, min(2160, int(max_width)))
    edge_h = max(64, min(2160, int(max_height)))
    parts.append(
        f"scale={edge_w}:{edge_h}:force_original_aspect_ratio=decrease:"
        "force_divisible_by=2:out_color_matrix=bt709:out_range=tv,"
        f"fps={PROXY_FPS},format=yuv420p,"
        "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv"
    )
    return ",".join(parts)


def cache_key_for(
    req: PlaybackProxyRequest,
    *,
    media_mtime_ns: int,
    media_size: int,
) -> str:
    payload = {
        "path": str(req.media_path.resolve()),
        "mtime_ns": media_mtime_ns,
        "size": media_size,
        "in": round(float(req.source_start_s), 6),
        "out": None if req.source_end_s is None else round(float(req.source_end_s), 6),
        "image": req.image.as_dict(),
        "look": req.look.as_dict(),
        "width": int(req.max_width),
        "height": int(req.max_height),
        "saturation": req.saturation,
        "fps": PROXY_FPS,
        "crf": PROXY_CRF,
        "preset": PROXY_PRESET,
        "gop": PROXY_GOP_FRAMES,
        "v": PROXY_VERSION,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def render_playback_proxy(
    req: PlaybackProxyRequest,
    *,
    data_dir: Path,
    cache_dir: Path | None = None,
) -> Path:
    """Return a cached 720p proxy path, or render it atomically.

    Raises ``PlaybackProxyError`` for recoverable failures and
    ``LutMissingError`` when a referenced ``.cube`` is gone. A failed FFmpeg run
    never publishes a partial file: the result is moved into place only after a
    non-empty, successful encode.
    """
    if not look_needs_preview_still(req.look):
        raise PlaybackProxyError(
            "Assign a color file before building a playback proxy.",
            code="no_lut",
        )
    media = req.media_path
    if not media.is_file():
        raise PlaybackProxyError("This media file is missing.", code="media_missing")
    try:
        st = media.stat()
    except OSError as exc:
        raise PlaybackProxyError("Could not read this media file.", code="media_missing") from exc

    folder = cache_dir if cache_dir is not None else playback_proxies_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    if req.look.conversion_lut and req.look.conversion_confirmed:
        require_lut_asset(data_dir, req.look.conversion_lut)
    if req.look.creative_lut and req.look.creative_strength > 0:
        require_lut_asset(data_dir, req.look.creative_lut)
    key = cache_key_for(req, media_mtime_ns=st.st_mtime_ns, media_size=st.st_size)
    dest = folder / f"{key}.mp4"
    if dest.is_file() and dest.stat().st_size > 0:
        return dest

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise PlaybackProxyError(
            "Install ffmpeg or: pip install imageio-ffmpeg",
            code="ffmpeg_missing",
        )
    work = folder / "work" / uuid.uuid4().hex
    work.mkdir(parents=True, exist_ok=True)
    temp = work / "proxy.mp4"
    try:
        try:
            vf = proxy_filter_chain(
                req,
                data_dir=data_dir,
                work_dir=work,
                max_width=req.max_width,
                max_height=req.max_height,
                saturation=req.saturation,
            )
        except LutMissingError:
            raise
        except Exception as exc:
            raise PlaybackProxyError(str(exc) or "Invalid color look.", code="lut_invalid") from exc

        start = max(0.0, float(req.source_start_s))
        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(media),
        ]
        if req.source_end_s is not None:
            duration = max(0.0, float(req.source_end_s) - start)
            cmd.extend(["-t", f"{duration:.3f}"])
        cmd.extend(
            [
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                PROXY_PRESET,
                "-crf",
                str(PROXY_CRF),
                "-g",
                str(PROXY_GOP_FRAMES),
                "-keyint_min",
                str(PROXY_GOP_FRAMES),
                "-sc_threshold",
                "0",
                "-pix_fmt",
                "yuv420p",
                "-colorspace",
                "bt709",
                "-color_primaries",
                "bt709",
                "-color_trc",
                "bt709",
                "-color_range",
                "tv",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                str(temp),
            ]
        )
        started = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=PROXY_FFMPEG_TIMEOUT_S,
                **subprocess_no_window_kwargs(),
            )
        except subprocess.TimeoutExpired as exc:
            raise PlaybackProxyError(
                "Building the playback proxy took too long.",
                code="proxy_timeout",
            ) from exc
        except OSError as exc:
            raise PlaybackProxyError(
                "Could not run ffmpeg for the playback proxy.",
                code="proxy_failed",
            ) from exc
        elapsed = time.perf_counter() - started
        logger.info("playback proxy rendered in %.2fs (%s)", elapsed, media.name)
        if proc.returncode != 0 or not temp.is_file() or temp.stat().st_size <= 0:
            detail = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
            raise PlaybackProxyError(
                detail or "Could not build the playback proxy.",
                code="proxy_failed",
            )
        temp.replace(dest)
        return dest
    finally:
        shutil.rmtree(work, ignore_errors=True)
