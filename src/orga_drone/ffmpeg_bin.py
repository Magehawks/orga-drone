"""Locate ffmpeg / ffprobe executables (PATH or bundled imageio-ffmpeg)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)
# imageio-ffmpeg 0.6.0 ships ffmpeg v7.1 which crashes on odd scaled heights
# (#369). requirements.txt pins >=0.8.0; warn when a stale user install wins.
_MIN_IMAGEIO_FFMPEG = (0, 8, 0)
_stale_imageio_warned = False


def _warn_if_stale_imageio_ffmpeg() -> None:
    global _stale_imageio_warned
    if _stale_imageio_warned:
        return
    try:
        import importlib.metadata as metadata

        version = metadata.version("imageio-ffmpeg")
        parts = tuple(int(part) for part in version.split(".")[:3])
    except Exception:
        return
    if parts < _MIN_IMAGEIO_FFMPEG:
        _stale_imageio_warned = True
        _LOG.warning(
            "imageio-ffmpeg %s is below the required >=0.8.0 floor; "
            "odd preview-still heights can crash ffmpeg (#369). "
            "Run: pip install 'imageio-ffmpeg>=0.8.0'",
            version,
        )


def find_ffmpeg() -> str | None:
    which = shutil.which("ffmpeg")
    if which:
        return which
    try:
        import imageio_ffmpeg

        _warn_if_stale_imageio_ffmpeg()
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
    startup_cls = getattr(subprocess, "STARTUPINFO", None)
    show_flag = getattr(subprocess, "STARTF_USESHOWWINDOW", None)
    hide = getattr(subprocess, "SW_HIDE", None)
    if startup_cls is None or show_flag is None or hide is None:
        return {"creationflags": flag}
    startupinfo = startup_cls()
    startupinfo.dwFlags |= show_flag
    startupinfo.wShowWindow = hide
    return {"creationflags": flag, "startupinfo": startupinfo}


def subprocess_below_normal_kwargs() -> dict[str, Any]:
    """No-window kwargs plus below-normal CPU priority for preview work.

    Studio stills and playback proxies run while the user keeps editing. A
    below-normal process keeps the WebView2 UI and video decode responsive on
    small machines. Exports keep normal priority.
    """
    kwargs = subprocess_no_window_kwargs()
    if sys.platform != "win32":
        return kwargs
    priority = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
    if not priority:
        return kwargs
    kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | priority
    return kwargs
