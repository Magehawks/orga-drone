"""Regression tests for the ffmpeg odd-height preview-still crash (#369).

The imageio-ffmpeg 0.6.0 binary (ffmpeg-win-x86_64-v7.1) crashes with
0xC0000374/0xC0000005 when the preview-still scale filter produces an odd
output height followed by ``format=yuv420p`` (issue #369). Requirements now
pin ``imageio-ffmpeg>=0.8.0`` (v9.0.2 binary, verified unaffected). These
tests keep the tripwire: any environment that resolves an affected binary
fails here with the measured crash matrix instead of failing silently at
runtime.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs

# (source_width, source_height, max_edge, expected fitted height)
_ODD_HEIGHT_CASES = [
    (1280, 720, 720, 405),   # old PREVIEW_MAX_EDGE: 16:9 fits to 720x405
    (1280, 719, 1080, 607),  # current PREVIEW_MAX_EDGE with odd aspect
]
_EVEN_HEIGHT_CASES = [
    (1280, 720, 1080, 608),  # current tip: 16:9 fits to 1080x608
    (1280, 722, 720, 406),
]


def _still_chain(max_edge: int) -> str:
    """The exact neutral preview-still chain from studio_preview_frame."""
    return (
        f"scale={max_edge}:{max_edge}:force_original_aspect_ratio=decrease"
        ":out_color_matrix=bt709:out_range=tv,"
        "format=yuv420p,setparams=colorspace=bt709:color_primaries=bt709"
        ":color_trc=bt709:range=tv,"
        "scale=in_color_matrix=bt709:in_range=tv,format=rgb24,"
        "scale=out_color_matrix=bt601:out_range=pc,format=yuvj420p,"
        "setparams=colorspace=bt470bg:range=pc"
    )


def _run_still(tmp_path: Path, width: int, height: int, max_edge: int) -> subprocess.CompletedProcess:
    ffmpeg = find_ffmpeg()
    assert ffmpeg, "ffmpeg binary required"
    photo = tmp_path / f"p-{width}x{height}.jpg"
    Image.new("RGB", (width, height), (143, 166, 184)).save(photo, quality=98, subsampling=0)
    return subprocess.run(
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(photo), "-frames:v", "1",
            "-vf", _still_chain(max_edge), "-q:v", "3",
            str(tmp_path / "frame.jpg"),
        ],
        capture_output=True,
        timeout=60,
        **subprocess_no_window_kwargs(),
    )


@pytest.mark.parametrize("width,height,max_edge,expected_height", _ODD_HEIGHT_CASES + _EVEN_HEIGHT_CASES)
def test_preview_still_chain_survives_fitted_heights(
    tmp_path: Path, width: int, height: int, max_edge: int, expected_height: int
) -> None:
    """The still chain must exit 0 for even AND odd fitted heights.

    An affected v7.1 binary exits 3221226356 (0xC0000374) on the odd cases
    and 3221225477 (0xC0000005) on 1080x607 — see issue #369's matrix.
    """
    result = _run_still(tmp_path, width, height, max_edge)
    assert result.returncode == 0, (
        f"ffmpeg exited {result.returncode} "
        f"(0x{result.returncode & 0xFFFFFFFF:08X}) for a {width}x{height} "
        f"source fitted to {max_edge} (expected fitted height {expected_height}); "
        "this is the #369 odd-height crash — upgrade imageio-ffmpeg to >=0.8",
        result.stderr[:400],
    )


def test_requirements_pin_imageio_ffmpeg_above_broken_release() -> None:
    """The dependency floor excludes the crashing 0.6.0/v7.1 binary."""
    text = Path("requirements.txt").read_text(encoding="utf-8")
    line = next(line for line in text.splitlines() if line.startswith("imageio-ffmpeg"))
    floor = line.split(">=")[1].strip()
    assert tuple(int(part) for part in floor.split(".")) >= (0, 8, 0), line
