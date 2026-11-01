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

from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_below_normal_kwargs
from orga_drone.studio_color_wheels import ColorWheels, ffmpeg_color_wheels_chain
from orga_drone.studio_hsl import HslAdjust, ffmpeg_hsl_chain
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
PROXY_CRF = 23
PROXY_PRESET = "ultrafast"
PROXY_GOP_FRAMES = 30
PROXY_FFMPEG_TIMEOUT_S = 180.0
PROXY_FFMPEG_TIMEOUT_MAX_S = 1800.0
PROXY_TIMEOUT_REALTIME_FACTOR = 8.0
PROXY_VERSION = 3
PROXY_CACHE_MAX_BYTES = 512 * 1024 * 1024
PROXY_CACHE_MAX_AGE_S = 14 * 24 * 60 * 60
PROXY_ORPHAN_WORK_AGE_S = 6 * 60 * 60


@dataclass(frozen=True)
class PlaybackProxyRequest:
    """Inputs for one static-LUT single-clip playback proxy."""

    media_path: Path
    source_start_s: float = 0.0
    source_end_s: float | None = None
    image: ImageAdjust = field(default_factory=ImageAdjust)
    look: ColorLook = field(default_factory=ColorLook)
    hsl: HslAdjust = field(default_factory=HslAdjust)
    color_wheels: ColorWheels = field(default_factory=ColorWheels)
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


def proxy_timeout_for(clip_duration_s: float) -> float:
    """Scale the FFmpeg budget for real long 4K clips, with a hard cap."""
    try:
        duration = float(clip_duration_s)
    except (TypeError, ValueError):
        return PROXY_FFMPEG_TIMEOUT_S
    if duration != duration or duration <= 0:
        return PROXY_FFMPEG_TIMEOUT_S
    scaled = duration * PROXY_TIMEOUT_REALTIME_FACTOR
    return max(PROXY_FFMPEG_TIMEOUT_S, min(PROXY_FFMPEG_TIMEOUT_MAX_S, scaled))


def _lut_digests(req: PlaybackProxyRequest, data_dir: Path) -> dict[str, str]:
    """Content hashes for every LUT that actually participates in the render."""
    names: set[str] = set()
    if req.look.conversion_lut and req.look.conversion_confirmed:
        names.add(req.look.conversion_lut)
    if req.look.creative_lut and req.look.creative_strength > 0:
        names.add(req.look.creative_lut)
    digests: dict[str, str] = {}
    for name in sorted(names):
        path = require_lut_asset(data_dir, name)
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digests[name] = digest.hexdigest()
    return digests


def _safe_unlink(path: Path, folder: Path) -> bool:
    try:
        resolved = path.resolve()
        if resolved.parent != folder:
            return False
        path.unlink()
        return True
    except OSError:
        return False


def cleanup_playback_proxies(
    cache_dir: Path,
    *,
    max_bytes: int = PROXY_CACHE_MAX_BYTES,
    max_age_s: int = PROXY_CACHE_MAX_AGE_S,
    orphan_age_s: int = PROXY_ORPHAN_WORK_AGE_S,
    now: float | None = None,
    keep: Path | None = None,
) -> int:
    """Remove expired/oversized proxies and old work dirs inside the cache only."""
    folder = Path(cache_dir).resolve()
    if not folder.is_dir():
        return 0
    now_s = time.time() if now is None else now
    keep_path = keep.resolve() if keep is not None else None
    removed = 0
    entries: list[tuple[float, int, Path]] = []
    total = 0
    for path in folder.glob("*.mp4"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((stat.st_mtime, stat.st_size, path))
        total += stat.st_size
    for mtime, size, path in entries:
        if keep_path is not None and path.resolve() == keep_path:
            continue
        if max_age_s > 0 and now_s - mtime > max_age_s:
            if _safe_unlink(path, folder):
                total -= size
                removed += 1
    remaining = [entry for entry in entries if entry[2].is_file()]
    remaining.sort(key=lambda entry: entry[0])
    for _mtime, size, path in remaining:
        if total <= max_bytes:
            break
        if keep_path is not None and path.resolve() == keep_path:
            continue
        if _safe_unlink(path, folder):
            total -= size
            removed += 1
    work = folder / "work"
    if work.is_dir() and orphan_age_s > 0:
        for child in work.iterdir():
            try:
                if not child.is_dir() or child.resolve().parent != work.resolve():
                    continue
                stat = child.stat()
                if now_s - stat.st_mtime > orphan_age_s:
                    shutil.rmtree(child, ignore_errors=True)
                    removed += 1
            except OSError:
                continue
    return removed


def proxy_filter_chain(
    req: PlaybackProxyRequest,
    *,
    data_dir: Path,
    work_dir: Path,
    max_width: int = PROXY_MAX_WIDTH,
    max_height: int = PROXY_MAX_HEIGHT,
    saturation: float = 1.0,
) -> str:
    """Scale first, then grade → LUT → HSL → wheels for a faster preview proxy.

    Export keeps grade → LUT → HSL → wheels → scale. The proxy is a preview
    artifact, so downscaling before the per-pixel LUT stages cuts generation
    time substantially; measured mean color difference against the export order
    stays below 2.4/255 on the real 4K fixture.
    """
    edge_w = max(64, min(2160, int(max_width)))
    edge_h = max(64, min(2160, int(max_height)))
    parts: list[str] = [
        f"scale={edge_w}:{edge_h}:force_original_aspect_ratio=decrease:"
        "force_divisible_by=2:out_color_matrix=bt709:out_range=tv"
    ]
    grade = ffmpeg_grade_chain(req.image)
    if grade:
        parts.append(grade)
    if not req.look.is_neutral:
        lut = ffmpeg_lut_chain(req.look, data_dir=data_dir, work_dir=work_dir)
        if lut:
            parts.append(lut)
    if not req.hsl.is_neutral:
        parts.append(ffmpeg_hsl_chain(req.hsl, data_dir=data_dir))
    if not req.color_wheels.is_neutral:
        parts.append(ffmpeg_color_wheels_chain(req.color_wheels, data_dir=data_dir))
    if saturation != 1.0:
        parts.append(f"eq=saturation={max(0.0, min(1.0, saturation)):.6f}")
    parts.append(
        f"fps={PROXY_FPS},format=yuv420p,"
        "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv"
    )
    return ",".join(parts)


def cache_key_for(
    req: PlaybackProxyRequest,
    *,
    media_mtime_ns: int,
    media_size: int,
    data_dir: Path,
) -> str:
    payload = {
        "path": str(req.media_path.resolve()),
        "mtime_ns": media_mtime_ns,
        "size": media_size,
        "in": round(float(req.source_start_s), 6),
        "out": None if req.source_end_s is None else round(float(req.source_end_s), 6),
        "image": req.image.as_dict(),
        "look": req.look.as_dict(),
        "hsl": req.hsl.as_dict(),
        "color_wheels": req.color_wheels.as_dict(),
        "lut_content": _lut_digests(req, data_dir),
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


def cached_playback_proxy(
    req: PlaybackProxyRequest,
    *,
    data_dir: Path,
    cache_dir: Path | None = None,
) -> Path | None:
    """Return an already generated proxy path without starting FFmpeg."""
    if not req.media_path.is_file():
        return None
    try:
        st = req.media_path.stat()
    except OSError:
        return None
    folder = cache_dir if cache_dir is not None else playback_proxies_dir(data_dir)
    try:
        key = cache_key_for(
            req,
            media_mtime_ns=st.st_mtime_ns,
            media_size=st.st_size,
            data_dir=data_dir,
        )
    except LutMissingError:
        return None
    path = folder / f"{key}.mp4"
    if path.is_file() and path.stat().st_size > 0:
        return path
    return None


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
    if (
        not look_needs_preview_still(req.look)
        and req.hsl.is_neutral
        and req.color_wheels.is_neutral
    ):
        raise PlaybackProxyError(
            "Assign a color file, HSL adjustment, or colour wheels before building a playback proxy.",
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
    key = cache_key_for(
        req,
        media_mtime_ns=st.st_mtime_ns,
        media_size=st.st_size,
        data_dir=data_dir,
    )
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
        duration_s = None
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
            duration_s = duration
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
                timeout=proxy_timeout_for(duration_s or 0.0),
                **subprocess_below_normal_kwargs(),
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
        try:
            current = media.stat()
            current_key = cache_key_for(
                req,
                media_mtime_ns=current.st_mtime_ns,
                media_size=current.st_size,
                data_dir=data_dir,
            )
        except (OSError, LutMissingError) as exc:
            raise PlaybackProxyError(
                "Proxy inputs changed while rendering.",
                code="superseded",
            ) from exc
        if current_key != key:
            raise PlaybackProxyError(
                "Proxy inputs changed while rendering.",
                code="superseded",
            )
        temp.replace(dest)
        cleanup_playback_proxies(folder, keep=dest)
        return dest
    finally:
        shutil.rmtree(work, ignore_errors=True)
