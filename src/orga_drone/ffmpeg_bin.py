"""Locate ffmpeg / ffprobe executables (PATH or bundled imageio-ffmpeg)."""

from __future__ import annotations

import shutil
from pathlib import Path


def find_ffmpeg() -> str | None:
    which = shutil.which("ffmpeg")
    if which:
        return which
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def find_ffprobe() -> str | None:
    """Optional; imageio-ffmpeg usually ships ffmpeg only."""
    which = shutil.which("ffprobe")
    if which:
        return which
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    sibling = Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix)
    if sibling.is_file():
        return str(sibling)
    return None


def ffmpeg_available() -> bool:
    return find_ffmpeg() is not None
