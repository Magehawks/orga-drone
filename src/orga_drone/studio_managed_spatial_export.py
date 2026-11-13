"""Materialize spatial managed grades for preview/export (#356/#357).

Pointwise grades stay on the lut3d bake path. Spatial selections cannot fold
into a global cube, so this module writes a temporary graded copy. Source
media is never overwritten.

Photo materialization is eager. Video materialization is intended for the
export job phase (cancel + progress). Graded video keeps source duration/fps
so trim/speed/repeat/transition stay on the canonical FFmpeg encoder path.
Audio is remuxed (copy when MP4-compatible, otherwise AAC).

Limits: sources up to ``MAX_SPATIAL_VIDEO_*``. Oversized clips fail closed.
When ffprobe is present, avg/r_frame_rate mismatches fail closed as VFR.
Without ffprobe (bundled imageio-ffmpeg), extract forces ``-vf fps=`` at the
probed rate so audio/video stay aligned (VFR is resampled, not silently
passthrough). Intermediate encode is a documented second lossy pass
(CRF 18 yuv420p) before the final export encode.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from orga_drone.ffmpeg_bin import find_ffmpeg, find_ffprobe, subprocess_no_window_kwargs
from orga_drone.studio_managed_apply import (
    ManagedApplyError,
    apply_managed_grade_image,
)

ProgressFn = Callable[[float], None]

# Soft product limits for the CPU reference video path (not a performance claim).
MAX_SPATIAL_VIDEO_PIXELS = 1920 * 1080
MAX_SPATIAL_VIDEO_DURATION_S = 60.0
MAX_SPATIAL_VIDEO_FRAMES = 900
# Combined decode+grade scratch budget (~uncompressed RGB8 frame equivalents).
# Source frames are deleted after each grade to keep only one PNG set on disk.
MAX_SPATIAL_VIDEO_PIXEL_FRAMES = MAX_SPATIAL_VIDEO_PIXELS * 300

_FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*fps", re.IGNORECASE)
_SIZE_RE = re.compile(r",\s*(\d{2,5})x(\d{2,5})\b")
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def source_identity(path: Path) -> str:
    """Stable cache fragment from path + size + mtime."""
    try:
        st = path.stat()
    except OSError as exc:
        raise ManagedApplyError("source media is missing", code="MEDIA_MISSING") from exc
    payload = f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def spatial_work_dir(base: Path, *, grade_digest: str, source: Path) -> Path:
    """Work directory that cannot collide across different source files."""
    return base / f"spatial_{grade_digest[:16]}_{source_identity(source)}"


def _story_time_for_source_pts(
    *,
    source_pts_s: float,
    source_in_s: float,
    story_anchor_s: float | None,
    playback_speed: float,
) -> float | None:
    """Map absolute media PTS to Story time for a constant-speed single play.

    ``None`` leaves RenderContext on the source-local default (source-local
    animation only). Story-local animation requires an explicit anchor.
    """
    if story_anchor_s is None:
        return None
    speed = max(1e-6, float(playback_speed))
    source_local = max(0.0, float(source_pts_s) - float(source_in_s))
    return float(story_anchor_s) + source_local / speed


def _grade_rgb_image(
    path: Path,
    grade: Mapping[str, Any],
    dest: Path,
    *,
    lattice_domain: str = "srgb",
    source_time_s: float = 0.0,
    source_in_s: float = 0.0,
    source_out_s: float | None = None,
    story_anchor_s: float | None = None,
    playback_speed: float = 1.0,
) -> Path:
    from PIL import Image

    from orga_drone.studio_grade_animation import (
        grade_has_animation,
        materialize_grade_at,
        render_context_for_source_sample,
    )

    active_grade: Mapping[str, Any] = grade
    if grade_has_animation(grade):
        active_grade = materialize_grade_at(
            grade,
            render_context_for_source_sample(
                source_id="spatial-still",
                source_pts_s=float(source_time_s),
                source_in_s=float(source_in_s),
                source_out_s=source_out_s,
                story_time_s=_story_time_for_source_pts(
                    source_pts_s=float(source_time_s),
                    source_in_s=float(source_in_s),
                    story_anchor_s=story_anchor_s,
                    playback_speed=playback_speed,
                ),
                speed=float(playback_speed),
            ),
        )
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        flat = list(rgb.getdata())
        rows = [
            [
                (
                    flat[y * width + x][0] / 255.0,
                    flat[y * width + x][1] / 255.0,
                    flat[y * width + x][2] / 255.0,
                )
                for x in range(width)
            ]
            for y in range(height)
        ]
        graded = apply_managed_grade_image(
            rows, active_grade, lattice_domain=lattice_domain
        )
        out = Image.new("RGB", (width, height))
        out.putdata(
            [
                (
                    int(min(255, max(0, round(sample[0] * 255)))),
                    int(min(255, max(0, round(sample[1] * 255)))),
                    int(min(255, max(0, round(sample[2] * 255)))),
                )
                for row in graded
                for sample in row
            ]
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        out.save(dest, format="PNG")
    return dest


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ManagedApplyError(
            "Spatial managed video grading was cancelled",
            code="CANCELLED",
        )


def _run_ffmpeg(
    args: list[str],
    *,
    timeout: int = 600,
    cancel_event: threading.Event | None = None,
) -> subprocess.CompletedProcess[bytes]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise ManagedApplyError(
            "Spatial managed video grades need ffmpeg",
            code="UNSUPPORTED_GRADE",
        )
    _check_cancel(cancel_event)
    try:
        proc = subprocess.Popen(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **subprocess_no_window_kwargs(),
        )
    except OSError as exc:
        raise ManagedApplyError(
            "Could not start ffmpeg for spatial managed video",
            code="UNSUPPORTED_GRADE",
        ) from exc
    try:
        elapsed = 0.0
        step = 0.25
        while True:
            _check_cancel(cancel_event)
            try:
                stdout, stderr = proc.communicate(timeout=step)
                return subprocess.CompletedProcess(
                    proc.args, proc.returncode, stdout, stderr
                )
            except subprocess.TimeoutExpired:
                elapsed += step
                if elapsed >= timeout:
                    proc.kill()
                    proc.wait(timeout=10)
                    raise ManagedApplyError(
                        "Spatial managed video grading timed out",
                        code="UNSUPPORTED_GRADE",
                    ) from None
    except ManagedApplyError:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        raise


def _parse_fps_fraction(value: str) -> float | None:
    text = value.strip()
    if not text or text in {"0/0", "N/A"}:
        return None
    if "/" in text:
        num_s, den_s = text.split("/", 1)
        try:
            num = float(num_s)
            den = float(den_s)
        except ValueError:
            return None
        if den == 0:
            return None
        return num / den
    try:
        return float(text)
    except ValueError:
        return None


def _probe_video_meta(path: Path) -> tuple[int, int, float, float]:
    """Return width, height, fps, duration_s.

    Prefer ffprobe (CFR check via avg vs r_frame_rate). Without ffprobe
    (bundled imageio-ffmpeg), fall back to ``ffmpeg -i`` and force CFR during
    frame extract with ``-vf fps=``. Unknown duration fails closed.
    """
    ffprobe = find_ffprobe()
    if ffprobe:
        try:
            proc = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_streams",
                    "-show_format",
                    "-select_streams",
                    "v:0",
                    str(path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
                **subprocess_no_window_kwargs(),
            )
        except (OSError, subprocess.SubprocessError):
            proc = None
        if proc is not None and proc.returncode == 0 and proc.stdout:
            try:
                data = json.loads(proc.stdout)
            except json.JSONDecodeError:
                data = None
            if data is not None:
                streams = data.get("streams") or []
                stream = streams[0] if streams else None
                if isinstance(stream, dict):
                    try:
                        width = int(stream.get("width") or 0)
                        height = int(stream.get("height") or 0)
                    except (TypeError, ValueError):
                        width = height = 0
                    avg = _parse_fps_fraction(str(stream.get("avg_frame_rate") or ""))
                    r_fps = _parse_fps_fraction(str(stream.get("r_frame_rate") or ""))
                    if (
                        avg is not None
                        and r_fps is not None
                        and abs(avg - r_fps) / max(avg, r_fps) > 0.01
                    ):
                        raise ManagedApplyError(
                            "Spatial managed video needs constant frame rate",
                            code="UNSUPPORTED_GRADE",
                        )
                    fps = avg or r_fps
                    duration = 0.0
                    if stream.get("duration") is not None:
                        try:
                            duration = float(stream["duration"])
                        except (TypeError, ValueError):
                            duration = 0.0
                    if duration <= 0:
                        fmt = data.get("format") or {}
                        try:
                            duration = float(fmt.get("duration") or 0)
                        except (TypeError, ValueError):
                            duration = 0.0
                    if width >= 2 and height >= 2 and fps and fps > 0 and duration > 0:
                        return width, height, float(fps), float(duration)

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise ManagedApplyError(
            "Spatial managed video grades need ffmpeg",
            code="UNSUPPORTED_GRADE",
        )
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        check=False,
        capture_output=True,
        timeout=60,
        **subprocess_no_window_kwargs(),
    )
    text = (proc.stderr or b"").decode("utf-8", errors="replace")
    # Match extract mapping ``0:v:0``: use the first video stream's WxH/fps.
    size = _SIZE_RE.search(text)
    if size is None:
        raise ManagedApplyError(
            "Could not probe spatial video dimensions or frame rate",
            code="UNSUPPORTED_GRADE",
        )
    width, height = int(size.group(1)), int(size.group(2))
    fps_m = _FPS_RE.search(text)
    dur_m = _DURATION_RE.search(text)
    if fps_m is None or dur_m is None:
        raise ManagedApplyError(
            "Could not probe spatial video dimensions or frame rate",
            code="UNSUPPORTED_GRADE",
        )
    fps = float(fps_m.group(1))
    hours = int(dur_m.group(1))
    minutes = int(dur_m.group(2))
    seconds = float(dur_m.group(3))
    duration = hours * 3600 + minutes * 60 + seconds
    if width < 2 or height < 2 or fps <= 0 or duration <= 0:
        raise ManagedApplyError(
            "Spatial video has invalid dimensions or frame rate",
            code="UNSUPPORTED_GRADE",
        )
    return width, height, fps, duration


def _source_has_audio(path: Path) -> bool:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        check=False,
        capture_output=True,
        timeout=60,
        **subprocess_no_window_kwargs(),
    )
    text = (proc.stderr or b"").decode("utf-8", errors="replace").lower()
    return " audio:" in text or "\naudio:" in text


def validate_spatial_video_limits(path: Path) -> tuple[int, int, float, float]:
    """Probe and enforce CPU-path limits without grading."""
    width, height, fps, duration = _probe_video_meta(path)
    pixels = width * height
    if pixels > MAX_SPATIAL_VIDEO_PIXELS:
        raise ManagedApplyError(
            "Spatial managed video is larger than the CPU grade limit",
            code="UNSUPPORTED_GRADE",
        )
    if duration > MAX_SPATIAL_VIDEO_DURATION_S:
        raise ManagedApplyError(
            "Spatial managed video is longer than the CPU grade limit",
            code="UNSUPPORTED_GRADE",
        )
    estimated = int(duration * fps + 0.5)
    if estimated <= 0:
        raise ManagedApplyError(
            "Spatial video has invalid dimensions or frame rate",
            code="UNSUPPORTED_GRADE",
        )
    if estimated > MAX_SPATIAL_VIDEO_FRAMES:
        raise ManagedApplyError(
            "Spatial managed video has more frames than the CPU grade limit",
            code="UNSUPPORTED_GRADE",
        )
    if pixels * estimated > MAX_SPATIAL_VIDEO_PIXEL_FRAMES:
        raise ManagedApplyError(
            "Spatial managed video exceeds the CPU grade scratch budget",
            code="UNSUPPORTED_GRADE",
        )
    return width, height, fps, duration


def _atomic_replace(tmp: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp, dest)


def _grade_rgb_video(
    path: Path,
    grade: Mapping[str, Any],
    dest: Path,
    *,
    source_in_s: float = 0.0,
    source_out_s: float | None = None,
    story_anchor_s: float | None = None,
    playback_speed: float = 1.0,
    cancel_event: threading.Event | None = None,
    on_progress: ProgressFn | None = None,
) -> Path:
    """Grade every decoded frame and remux with source audio when present."""
    width, height, fps, duration = validate_spatial_video_limits(path)
    run_id = hashlib.sha1(f"{os.getpid()}|{dest}|{path}".encode()).hexdigest()[:10]
    frames_dir = dest.parent / f"frames_src_{run_id}"
    graded_dir = dest.parent / f"frames_graded_{run_id}"
    tmp_out = dest.parent / f"graded_{run_id}.tmp.mp4"
    for orphan in (frames_dir, graded_dir, tmp_out):
        if orphan.is_dir():
            shutil.rmtree(orphan, ignore_errors=True)
        elif orphan.is_file():
            orphan.unlink(missing_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)
    graded_dir.mkdir(parents=True, exist_ok=True)

    try:
        _check_cancel(cancel_event)
        # Force CFR at the probed rate so VFR sources cannot drift audio/video.
        fps_filter = f"{fps:.6f}".rstrip("0").rstrip(".")
        # Hard-cap extraction so a bad duration probe cannot fill the disk.
        frame_cap = min(
            MAX_SPATIAL_VIDEO_FRAMES,
            max(1, MAX_SPATIAL_VIDEO_PIXEL_FRAMES // max(1, width * height)),
            int(duration * fps + 1.5),
        )
        extract = _run_ffmpeg(
            [
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-vf",
                f"fps={fps_filter}",
                "-frames:v",
                str(frame_cap),
                "-start_number",
                "0",
                str(frames_dir / "frame_%06d.png"),
            ],
            timeout=900,
            cancel_event=cancel_event,
        )
        if extract.returncode != 0:
            raise ManagedApplyError(
                "Could not decode frames for spatial managed video",
                code="UNSUPPORTED_GRADE",
            )

        sources = sorted(frames_dir.glob("frame_*.png"))
        if not sources:
            raise ManagedApplyError(
                "Spatial managed video produced no frames",
                code="UNSUPPORTED_GRADE",
            )
        if len(sources) > MAX_SPATIAL_VIDEO_FRAMES:
            raise ManagedApplyError(
                "Spatial managed video has more frames than the CPU grade limit",
                code="UNSUPPORTED_GRADE",
            )
        total = len(sources)
        from orga_drone.studio_grade_animation import grade_has_animation

        animated = grade_has_animation(grade)
        for index, frame_path in enumerate(sources):
            _check_cancel(cancel_event)
            # Absolute media PTS for this extracted frame.
            pts_s = float(index) / float(fps) if fps > 0 else 0.0
            _grade_rgb_image(
                frame_path,
                grade,
                graded_dir / f"frame_{index:06d}.png",
                lattice_domain="encoded-bt709",
                source_time_s=pts_s if animated else 0.0,
                source_in_s=float(source_in_s),
                source_out_s=source_out_s,
                story_anchor_s=story_anchor_s if animated else None,
                playback_speed=float(playback_speed),
            )
            frame_path.unlink(missing_ok=True)
            if on_progress is not None and (index % 5 == 0 or index + 1 == total):
                on_progress((index + 1) / float(total))

        fps_arg = f"{fps:.6f}".rstrip("0").rstrip(".")
        encode_args = [
            "-framerate",
            fps_arg,
            "-start_number",
            "0",
            "-i",
            str(graded_dir / "frame_%06d.png"),
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-movflags",
            "+faststart",
        ]
        has_audio = _source_has_audio(path)
        if has_audio:
            encode_args.extend(["-map", "1:a:0?", "-c:a", "copy", "-shortest"])
        else:
            encode_args.append("-an")
        encode_args.append(str(tmp_out))

        encode = _run_ffmpeg(encode_args, timeout=900, cancel_event=cancel_event)
        if encode.returncode != 0 or not tmp_out.is_file() or tmp_out.stat().st_size <= 0:
            if has_audio:
                # Retry with AAC when stream copy cannot mux into MP4.
                if tmp_out.is_file():
                    tmp_out.unlink(missing_ok=True)
                encode_args = [
                    "-framerate",
                    fps_arg,
                    "-start_number",
                    "0",
                    "-i",
                    str(graded_dir / "frame_%06d.png"),
                    "-i",
                    str(path),
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0?",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-crf",
                    "18",
                    "-colorspace",
                    "bt709",
                    "-color_primaries",
                    "bt709",
                    "-color_trc",
                    "bt709",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-shortest",
                    "-movflags",
                    "+faststart",
                    str(tmp_out),
                ]
                encode = _run_ffmpeg(
                    encode_args, timeout=900, cancel_event=cancel_event
                )
            if (
                encode.returncode != 0
                or not tmp_out.is_file()
                or tmp_out.stat().st_size <= 0
            ):
                raise ManagedApplyError(
                    "Could not encode spatial managed video",
                    code="UNSUPPORTED_GRADE",
                )
        _atomic_replace(tmp_out, dest)
        if on_progress is not None:
            on_progress(1.0)
        return dest
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)
        shutil.rmtree(graded_dir, ignore_errors=True)
        if tmp_out.is_file():
            tmp_out.unlink(missing_ok=True)
        # Silence unused meta when probe succeeded but encode failed early.
        _ = (width, height, duration)


def materialize_spatial_managed_media(
    source: Path,
    grade: Mapping[str, Any],
    work_dir: Path,
    *,
    kind: str,
    grade_digest: str | None = None,
    source_in_s: float = 0.0,
    source_out_s: float | None = None,
    story_anchor_s: float | None = None,
    playback_speed: float = 1.0,
    cancel_event: threading.Event | None = None,
    on_progress: ProgressFn | None = None,
) -> Path:
    """Return a temporary graded media path under ``work_dir``.

    Video grades keep full source timing so callers can preserve trim/speed/
    repeat on the export clip. Partial outputs never become cache hits.
    Story-local animation requires an explicit ``story_anchor_s`` (clip Story
    start) and a constant-speed single play; repeats/ramps stay fail-closed at
    the export owner.
    """
    from orga_drone.studio_grade_animation import grade_uses_story_local_animation

    if not source.is_file():
        raise ManagedApplyError("source media is missing", code="MEDIA_MISSING")
    if kind not in {"photo", "video"}:
        raise ManagedApplyError(
            "Unsupported spatial media kind",
            code="UNSUPPORTED_GRADE",
        )
    if grade_uses_story_local_animation(grade) and story_anchor_s is None:
        raise ManagedApplyError(
            "Story-local grade animation needs an explicit Story anchor; "
            "full-source bake without Story mapping is refused",
            code="UNSUPPORTED_GRADE",
        )

    if grade_digest:
        work_dir = spatial_work_dir(work_dir, grade_digest=grade_digest, source=source)
        if story_anchor_s is not None:
            # Story mapping changes graded frames without changing grade digest.
            anchor_key = f"{float(story_anchor_s):.3f}_{float(playback_speed):.4f}"
            work_dir = work_dir / f"story_{hashlib.sha1(anchor_key.encode()).hexdigest()[:10]}"
    work_dir.mkdir(parents=True, exist_ok=True)

    if kind == "photo":
        dest = work_dir / "graded.png"
        if dest.is_file() and dest.stat().st_size > 0:
            return dest
        from orga_drone.export.studio_encoder import _materialize_photo_still

        still = work_dir / "source.jpg"
        _materialize_photo_still(source, still)
        tmp = work_dir / "graded.tmp.png"
        if tmp.is_file():
            tmp.unlink(missing_ok=True)
        _grade_rgb_image(
            still,
            grade,
            tmp,
            source_time_s=float(source_in_s),
            source_in_s=float(source_in_s),
            source_out_s=source_out_s,
            story_anchor_s=story_anchor_s,
            playback_speed=float(playback_speed),
        )
        _atomic_replace(tmp, dest)
        return dest

    dest = work_dir / "graded.mp4"
    if dest.is_file() and dest.stat().st_size > 0:
        try:
            validate_spatial_video_limits(dest)
            return dest
        except ManagedApplyError:
            dest.unlink(missing_ok=True)
    return _grade_rgb_video(
        source,
        grade,
        dest,
        source_in_s=float(source_in_s),
        source_out_s=source_out_s,
        story_anchor_s=story_anchor_s,
        playback_speed=float(playback_speed),
        cancel_event=cancel_event,
        on_progress=on_progress,
    )
