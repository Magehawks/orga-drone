"""Locate ffmpeg / ffprobe executables (PATH or bundled imageio-ffmpeg)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


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


def subprocess_no_window_kwargs() -> dict[str, Any]:
    """Extra kwargs so Windows GUI apps do not flash a console for ffmpeg.

    Safe on Linux/macOS (returns ``{}``). Prefer ``subprocess.CREATE_NO_WINDOW``
    when available; never sets ``shell=True``.
    """
    if sys.platform != "win32":
        return {}
    flag = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if not flag:
        return {}
    return {"creationflags": flag}
