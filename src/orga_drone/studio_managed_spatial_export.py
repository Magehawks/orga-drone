"""Materialize spatial managed grades for preview/export (#356/#357).

Pointwise grades stay on the lut3d bake path. Spatial selections cannot fold
into a global cube, so this module writes a temporary graded copy. Source
media is never overwritten.

Photo and video spatial materialization share the CPU reference applicator.
Graded video preserves source duration/fps so Studio export can keep trims,
speed ramps, repeats, transitions, and soundtrack mixing on the existing
FFmpeg pipeline. Audio is copied from the source when present.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.studio_managed_apply import (
    ManagedApplyError,
    apply_managed_grade_image,
)

_FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*fps", re.IGNORECASE)
_SIZE_RE = re.compile(r",\s*(\d{2,5})x(\d{2,5})\b")


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


def _grade_rgb_image(path: Path, grade: Mapping[str, Any], dest: Path) -> Path:
    from PIL import Image

    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        px = rgb.load()
        rows = [
            [
                (px[x, y][0] / 255.0, px[x, y][1] / 255.0, px[x, y][2] / 255.0)
                for x in range(width)
            ]
            for y in range(height)
        ]
        graded = apply_managed_grade_image(rows, grade, lattice_domain="srgb")
        out = Image.new("RGB", (width, height))
        out_px = out.load()
        for y, row in enumerate(graded):
            for x, sample in enumerate(row):
                out_px[x, y] = (
                    int(min(255, max(0, round(sample[0] * 255)))),
                    int(min(255, max(0, round(sample[1] * 255)))),
                    int(min(255, max(0, round(sample[2] * 255)))),
                )
        dest.parent.mkdir(parents=True, exist_ok=True)
        out.save(dest, format="PNG")
    return dest


def _run_ffmpeg(args: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[bytes]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise ManagedApplyError(
            "ffmpeg is required for spatial managed video grades",
            code="UNSUPPORTED_GRADE",
        )
    try:
        return subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args],
            check=False,
            capture_output=True,
            timeout=timeout,
            **subprocess_no_window_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        raise ManagedApplyError(
            "Spatial managed video grading timed out",
            code="UNSUPPORTED_GRADE",
        ) from exc


def _probe_video_meta(path: Path) -> tuple[int, int, float]:
    """Return width, height, fps from ffmpeg -i stderr (works without ffprobe)."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise ManagedApplyError(
            "ffmpeg is required for spatial managed video grades",
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
    size = _SIZE_RE.search(text)
    fps_m = _FPS_RE.search(text)
    if size is None or fps_m is None:
        raise ManagedApplyError(
            "Could not probe spatial video dimensions/fps",
            code="UNSUPPORTED_GRADE",
        )
    width = int(size.group(1))
    height = int(size.group(2))
    fps = float(fps_m.group(1))
    if width < 2 or height < 2 or fps <= 0:
        raise ManagedApplyError(
            "Spatial video has invalid dimensions or fps",
            code="UNSUPPORTED_GRADE",
        )
    return width, height, fps


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


def _grade_rgb_video(path: Path, grade: Mapping[str, Any], dest: Path) -> Path:
    """Grade every decoded frame and remux with source audio when present.

    The graded MP4 keeps the source frame rate and frame count so export can
    retain source_start/source_end, speed ramps, repeats, and transitions on
    the canonical encoder path.
    """
    _width, _height, fps = _probe_video_meta(path)
    frames_dir = dest.parent / "frames_src"
    graded_dir = dest.parent / "frames_graded"
    if frames_dir.exists():
        shutil.rmtree(frames_dir, ignore_errors=True)
    if graded_dir.exists():
        shutil.rmtree(graded_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True, exist_ok=True)
    graded_dir.mkdir(parents=True, exist_ok=True)

    extract = _run_ffmpeg(
        [
            "-i",
            str(path),
            "-vsync",
            "0",
            "-start_number",
            "0",
            str(frames_dir / "frame_%06d.png"),
        ],
        timeout=900,
    )
    if extract.returncode != 0:
        detail = (extract.stderr or b"").decode("utf-8", errors="replace").strip()
        raise ManagedApplyError(
            detail or "Could not decode frames for spatial managed video",
            code="UNSUPPORTED_GRADE",
        )

    sources = sorted(frames_dir.glob("frame_*.png"))
    if not sources:
        raise ManagedApplyError(
            "Spatial managed video produced no frames",
            code="UNSUPPORTED_GRADE",
        )
    for index, frame_path in enumerate(sources):
        _grade_rgb_image(frame_path, grade, graded_dir / f"frame_{index:06d}.png")

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
    ]
    if _source_has_audio(path):
        encode_args.extend(["-map", "1:a:0?", "-c:a", "copy"])
    else:
        encode_args.append("-an")
    encode_args.extend(
        [
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            "-movflags",
            "+faststart",
            str(dest),
        ]
    )
    encode = _run_ffmpeg(encode_args, timeout=900)
    if encode.returncode != 0 or not dest.is_file() or dest.stat().st_size <= 0:
        detail = (encode.stderr or b"").decode("utf-8", errors="replace").strip()
        raise ManagedApplyError(
            detail or "Could not encode spatial managed video",
            code="UNSUPPORTED_GRADE",
        )
    # Drop intermediate frames after a successful encode to bound disk use.
    shutil.rmtree(frames_dir, ignore_errors=True)
    shutil.rmtree(graded_dir, ignore_errors=True)
    return dest


def materialize_spatial_managed_media(
    source: Path,
    grade: Mapping[str, Any],
    work_dir: Path,
    *,
    kind: str,
    grade_digest: str | None = None,
) -> Path:
    """Return a temporary graded media path under ``work_dir``.

    ``work_dir`` should already incorporate source identity (see
    ``spatial_work_dir``). Video grades keep full source timing so callers can
    preserve trim/speed/repeat on the export clip.
    """
    if not source.is_file():
        raise ManagedApplyError("source media is missing", code="MEDIA_MISSING")
    if kind not in {"photo", "video"}:
        raise ManagedApplyError(f"unsupported spatial kind: {kind}", code="UNSUPPORTED_GRADE")

    # Prefer an isolated work dir when the caller passes a shared base + digest.
    if grade_digest:
        work_dir = spatial_work_dir(work_dir, grade_digest=grade_digest, source=source)
    work_dir.mkdir(parents=True, exist_ok=True)

    if kind == "photo":
        dest = work_dir / "graded.png"
        if dest.is_file() and dest.stat().st_size > 0:
            return dest
        from orga_drone.export.studio_encoder import _materialize_photo_still

        still = work_dir / "source.jpg"
        _materialize_photo_still(source, still)
        return _grade_rgb_image(still, grade, dest)

    dest = work_dir / "graded.mp4"
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    return _grade_rgb_video(source, grade, dest)
