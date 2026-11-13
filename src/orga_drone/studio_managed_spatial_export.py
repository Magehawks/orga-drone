"""Materialize spatial managed grades for preview/export (#356/#357).

Pointwise grades stay on the lut3d bake path. Spatial selections cannot fold
into a global cube, so this module writes a temporary graded copy. Source
media is never overwritten.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_below_normal_kwargs
from orga_drone.studio_managed_apply import (
    ManagedApplyError,
    apply_managed_grade_image,
)


def _grade_rgb_image(path: Path, grade: Mapping[str, Any], dest: Path) -> Path:
    from PIL import Image

    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        raw = list(rgb.getdata())
        rows = [
            [
                (
                    raw[y * width + x][0] / 255.0,
                    raw[y * width + x][1] / 255.0,
                    raw[y * width + x][2] / 255.0,
                )
                for x in range(width)
            ]
            for y in range(height)
        ]
        graded = apply_managed_grade_image(rows, grade, lattice_domain="srgb")
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


def materialize_spatial_managed_media(
    source: Path,
    grade: Mapping[str, Any],
    work_dir: Path,
    *,
    kind: str,
    max_frames: int = 3600,
) -> Path:
    """Return a temporary graded media path under ``work_dir``."""
    if not source.is_file():
        raise ManagedApplyError("source media is missing", code="MEDIA_MISSING")
    work_dir.mkdir(parents=True, exist_ok=True)
    if kind == "photo":
        dest = work_dir / "graded.png"
        if dest.is_file() and dest.stat().st_size > 0:
            return dest
        from orga_drone.export.studio_encoder import _materialize_photo_still

        still = work_dir / "source.jpg"
        _materialize_photo_still(source, still)
        return _grade_rgb_image(still, grade, dest)

    if kind != "video":
        raise ManagedApplyError(f"unsupported spatial kind: {kind}", code="UNSUPPORTED_GRADE")

    dest = work_dir / "graded.mp4"
    if dest.is_file() and dest.stat().st_size > 0:
        return dest

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise ManagedApplyError("ffmpeg is required for spatial video export", code="FFMPEG_MISSING")

    frames_dir = work_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    pattern = frames_dir / "frame_%06d.png"
    extract = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vsync",
            "0",
            "-frames:v",
            str(max_frames),
            str(pattern),
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        **subprocess_below_normal_kwargs(),
    )
    if extract.returncode != 0:
        detail = (extract.stderr or b"").decode("utf-8", errors="replace").strip()
        raise ManagedApplyError(
            detail or "could not extract frames for spatial grade",
            code="SPATIAL_EXPORT",
        )

    frames = sorted(frames_dir.glob("frame_*.png"))
    if not frames:
        raise ManagedApplyError("no frames extracted for spatial grade", code="SPATIAL_EXPORT")
    graded_dir = work_dir / "graded-frames"
    graded_dir.mkdir(parents=True, exist_ok=True)
    for index, frame in enumerate(frames):
        _grade_rgb_image(frame, grade, graded_dir / f"frame_{index:06d}.png")

    assemble = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-framerate",
            "30",
            "-i",
            str(graded_dir / "frame_%06d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            str(dest),
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        **subprocess_below_normal_kwargs(),
    )
    if assemble.returncode != 0 or not dest.is_file():
        detail = (assemble.stderr or b"").decode("utf-8", errors="replace").strip()
        raise ManagedApplyError(
            detail or "could not assemble spatial graded video",
            code="SPATIAL_EXPORT",
        )
    return dest
