"""Studio Collage MP4 segment export (ADR 0038 / #462).

Reuses the WP4 still compositor for per-frame (or photo-hold) honesty so
preview and export share layout + grade application. Encodes via the existing
FFmpeg toolchain; does not invent a second encoder pipeline.

Issue #489 adds a free-space guard on the JPEG staging volume. The composed
frame sequence is unchanged; streaming or batched encoding remain separate
follow-ups after further evidence (#487).
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from orga_drone.db import Database
from orga_drone.export.studio_encoder import (
    EXPORT_FPS,
    ExportCancelled,
    StudioExportError,
    _run_ffmpeg,
    _segment_vf,
    _x264_video_args,
)
from orga_drone.ffmpeg_bin import find_ffmpeg
from orga_drone.studio_collage import iter_leaves, normalize_spec
from orga_drone.studio_collage_still import (
    EXPORT_LONG_EDGE,
    CollageExportFrames,
    compose_collage_rgba,
    refuse_canvas,
)


ProgressCb = Callable[[dict[str, Any]], None]

# Documented free-space reserve on the collage JPEG staging volume (#489).
# Exports abort before a next write would leave less than this remaining.
COLLAGE_STAGING_FREE_SPACE_RESERVE_BYTES = 1 * 1024**3

# TEST-ONLY: absolute free-byte simulation for the staging volume. When set,
# reported free space is max(0, int(env) - staged_bytes). Never fill a real disk.
COLLAGE_STAGING_FREE_BYTES_ENV = "ORGA_DRONE_COLLAGE_STAGING_FREE_BYTES"

COLLAGE_STAGING_DISK_FULL_MESSAGE = (
    "Not enough temporary disk space. Free up space and try again."
)
COLLAGE_STAGING_LOW_SPACE_MESSAGE = COLLAGE_STAGING_DISK_FULL_MESSAGE

# TEST-ONLY monkeypatch hooks used by disk-safety regressions.
_staging_free_bytes_override: int | None = None
_staging_free_bytes_provider: Callable[[Path], int] | None = None


def estimate_composed_jpeg_bytes(width: int, height: int) -> int:
    """Conservative upper bound for one quality-95 RGB JPEG at canvas size."""
    pixels = max(1, int(width) * int(height))
    return max(64_000, pixels // 2)


def usable_staging_free_bytes(path: Path, *, staged_bytes: int = 0) -> int:
    """Usable free bytes on the volume that holds ``path``.

    Production uses ``shutil.disk_usage``. Test hooks and the TEST-ONLY
    environment override simulate a shrinking budget without filling a disk.
    """
    if _staging_free_bytes_provider is not None:
        return max(0, int(_staging_free_bytes_provider(path)))
    if _staging_free_bytes_override is not None:
        return max(0, int(_staging_free_bytes_override) - max(0, int(staged_bytes)))
    # TEST-ONLY: absolute free-byte simulation when ORGA_DRONE_E2E=1.
    if os.environ.get("ORGA_DRONE_E2E") == "1":
        raw = os.environ.get(COLLAGE_STAGING_FREE_BYTES_ENV)
        if raw is not None and str(raw).strip() != "":
            try:
                budget = int(str(raw).strip())
            except ValueError as exc:
                raise StudioExportError(
                    COLLAGE_STAGING_DISK_FULL_MESSAGE,
                    code="collage_staging_disk_full",
                ) from exc
            return max(0, budget - max(0, int(staged_bytes)))
    return int(shutil.disk_usage(path).free)


def ensure_staging_space(
    path: Path,
    *,
    next_write_bytes: int,
    staged_bytes: int = 0,
    reserve_bytes: int = COLLAGE_STAGING_FREE_SPACE_RESERVE_BYTES,
) -> None:
    """Abort when the next write would breach the documented free-space reserve."""
    needed = max(0, int(next_write_bytes))
    reserve = max(0, int(reserve_bytes))
    free = usable_staging_free_bytes(path, staged_bytes=staged_bytes)
    if free - needed < reserve:
        raise StudioExportError(
            COLLAGE_STAGING_DISK_FULL_MESSAGE,
            code="collage_staging_disk_full",
        )


ensure_collage_staging_space = ensure_staging_space


def collage_has_video_leaf(spec: dict[str, Any]) -> bool:
    for leaf in iter_leaves(normalize_spec(spec)["root"]):
        media = leaf.get("media")
        if isinstance(media, dict) and str(media.get("kind") or "").lower() == "video":
            return True
    return False


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ExportCancelled()


def _emit(on_progress: ProgressCb | None, **payload: Any) -> None:
    if on_progress is not None:
        on_progress(payload)


def _canvas_to_rgb_jpeg(canvas, dest: Path) -> None:
    from PIL import Image

    if canvas.mode == "RGBA":
        bg = Image.new("RGB", canvas.size, (10, 12, 14))
        try:
            bg.paste(canvas, mask=canvas.split()[3])
            bg.save(dest, format="JPEG", quality=95, optimize=True, subsampling=0)
        finally:
            bg.close()
        return
    canvas.convert("RGB").save(dest, format="JPEG", quality=95, optimize=True, subsampling=0)


def _write_composed_jpeg(
    canvas,
    dest: Path,
    *,
    staged_bytes: int,
    next_write_bytes: int,
) -> int:
    """Guard, write one composed JPEG, and return bytes added on disk."""
    ensure_staging_space(
        dest.parent,
        next_write_bytes=next_write_bytes,
        staged_bytes=staged_bytes,
    )
    _canvas_to_rgb_jpeg(canvas, dest)
    return int(dest.stat().st_size)


def render_collage_mp4_segment(
    db: Database,
    spec: dict[str, Any],
    out: Path,
    *,
    width: int,
    height: int,
    duration_s: float,
    cancel_event: threading.Event | None = None,
    on_progress: ProgressCb | None = None,
    long_edge: int | None = None,
) -> Path:
    """Render one collage Story segment as a muted H.264 MP4."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise StudioExportError(
            "Install ffmpeg or: pip install imageio-ffmpeg",
            code="ffmpeg_missing",
        )
    normalized = normalize_spec(spec)
    dur = max(0.1, float(duration_s))
    edge = int(long_edge or max(int(width), int(height), EXPORT_LONG_EDGE))
    refuse_canvas(int(width), int(height))
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="orga-drone-collage-mp4-"))
    export_frames = CollageExportFrames(tmp_dir / "source-frames")
    staged_bytes = 0
    next_write = estimate_composed_jpeg_bytes(int(width), int(height))
    try:
        _check_cancel(cancel_event)
        ensure_staging_space(
            tmp_dir,
            next_write_bytes=next_write,
            staged_bytes=staged_bytes,
        )
        _emit(on_progress, phase="preparing", percent=5)
        if not collage_has_video_leaf(normalized):
            still = tmp_dir / "still.jpg"
            canvas = compose_collage_rgba(
                db,
                normalized,
                long_edge=edge,
                t_s=0.0,
                cancel_event=cancel_event,
                exact_time=True,
                export_frames=export_frames,
            )
            try:
                _check_cancel(cancel_event)
                written = _write_composed_jpeg(
                    canvas,
                    still,
                    staged_bytes=staged_bytes,
                    next_write_bytes=next_write,
                )
                staged_bytes += written
                next_write = max(next_write, written)
            finally:
                canvas.close()
            _emit(on_progress, phase="rendering", percent=40)
            cmd = [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-loop",
                "1",
                "-framerate",
                str(EXPORT_FPS),
                "-i",
                str(still),
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-t",
                f"{dur:.3f}",
                "-vf",
                _segment_vf(int(width), int(height)),
                *_x264_video_args(),
                "-c:a",
                "aac",
                "-ac",
                "2",
                "-ar",
                "48000",
                "-shortest",
                str(out),
            ]
            _run_ffmpeg(cmd, on_time=None, duration_s=dur, cancel_event=cancel_event)
            _emit(on_progress, phase="rendering", percent=95)
            if not out.is_file() or out.stat().st_size <= 0:
                raise StudioExportError("Could not write the collage video segment.")
            return out

        frame_count = max(1, int(round(dur * EXPORT_FPS)))
        frames_dir = tmp_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        for index in range(frame_count):
            _check_cancel(cancel_event)
            t_s = index / float(EXPORT_FPS)
            canvas = compose_collage_rgba(
                db,
                normalized,
                long_edge=edge,
                t_s=t_s,
                cancel_event=cancel_event,
                exact_time=True,
                export_frames=export_frames,
            )
            try:
                frame_path = frames_dir / f"frame_{index:06d}.jpg"
                written = _write_composed_jpeg(
                    canvas,
                    frame_path,
                    staged_bytes=staged_bytes,
                    next_write_bytes=next_write,
                )
                staged_bytes += written
                next_write = max(next_write, written)
            finally:
                canvas.close()
            if on_progress is not None and (index % 5 == 0 or index + 1 == frame_count):
                frac = (index + 1) / float(frame_count)
                _emit(
                    on_progress,
                    phase="rendering",
                    percent=int(10 + frac * 70),
                    clip_fraction=frac,
                )
        pattern = str(frames_dir / "frame_%06d.jpg")
        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-framerate",
            str(EXPORT_FPS),
            "-i",
            pattern,
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-frames:v",
            str(frame_count),
            "-vf",
            _segment_vf(int(width), int(height)),
            *_x264_video_args(),
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-shortest",
            str(out),
        ]
        _run_ffmpeg(cmd, on_time=None, duration_s=dur, cancel_event=cancel_event)
        _emit(on_progress, phase="rendering", percent=95)
        if not out.is_file() or out.stat().st_size <= 0:
            raise StudioExportError("Could not write the collage video segment.")
        return out
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
