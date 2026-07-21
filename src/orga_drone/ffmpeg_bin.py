"""Locate an ffmpeg executable (PATH or bundled imageio-ffmpeg)."""

from __future__ import annotations

import shutil


def find_ffmpeg() -> str | None:
    which = shutil.which("ffmpeg")
    if which:
        return which
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def ffmpeg_available() -> bool:
    return find_ffmpeg() is not None
