"""Compare actual MP4 pixels to pause/scrub JPEGs using synthetic media/LUTs."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat

from orga_drone.config import Settings
from orga_drone.export.studio_config import StudioExportClip, StudioExportConfig
from orga_drone.export.studio_encoder import FfmpegStudioEncoder
from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.studio_image import ImageAdjust
from orga_drone.studio_lut import ColorLook, LutMissingError, import_lut_from_path
from orga_drone.studio_preview_frame import PreviewFrameRequest, render_preview_frame


def _run(ffmpeg: str, *args: str) -> None:
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", *args], check=True,
                   capture_output=True, timeout=60, **subprocess_no_window_kwargs())


@pytest.mark.parametrize("conversion", [False, True])
def test_lut_strength_pixels_match_mp4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, conversion: bool,
) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg unavailable")
    data = tmp_path / "data"
    monkeypatch.setattr("orga_drone.config.settings", Settings(data_dir=data))
    video = tmp_path / "synthetic.mp4"
    # A changing source verifies the second scrub time, as well as color.
    _run(ffmpeg, "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video))
    original_hash = hashlib.sha256(video.read_bytes()).hexdigest()
    cube = tmp_path / "synthetic.cube"
    lines = ['TITLE "Synthetic channel transform"', 'LUT_3D_SIZE 2']
    for b in (0, 1):
        for g in (0, 1):
            for r in (0, 1):
                lines.append(f"{0.2 + r * 0.7} {g * 0.65} {b * 0.8}")
    cube.write_text("\n".join(lines) + "\n", encoding="utf-8")
    asset = import_lut_from_path(data, cube)
    means = []
    for strength in (0, 50, 100):
        look = ColorLook(
            input_profile="dlog_m" if conversion else "custom",
            conversion_lut=asset if conversion else "",
            conversion_confirmed=conversion,
            creative_lut=asset, creative_strength=strength,
        )
        grade = ImageAdjust(exposure=8, warmth=5, highlights=-5)
        clip = StudioExportClip(video, "video", 1.0, source_start_s=0.3,
                                source_end_s=1.3, image=grade, color_look=look)
        output = FfmpegStudioEncoder().render(StudioExportConfig(
            output_path=tmp_path / f"export-{strength}.mp4", width=320, height=180,
            clips=(clip,), quality="best",
        ))
        for local in (0.2, 0.6):
            still = render_preview_frame(PreviewFrameRequest(
                video, "video", 0.3 + local, grade, look, max_edge=320,
            ), data_dir=data)
            extracted = tmp_path / f"frame-{strength}-{local}.png"
            _run(ffmpeg, "-ss", str(local), "-i", str(output), "-frames:v", "1", str(extracted))
            with Image.open(still) as a, Image.open(extracted) as b:
                # JPEG + H264 chroma/scaling tolerances; dramatic LUT shifts fail.
                difference = ImageStat.Stat(ImageChops.difference(a.convert("RGB"), b.convert("RGB")))
                assert max(difference.mean) < 8, difference.mean
                if local == 0.2:
                    means.append(ImageStat.Stat(a.convert("RGB")).mean)
    assert max(abs(means[0][i] - means[2][i]) for i in range(3)) > 10
    assert means[0][1] > means[1][1] > means[2][1]
    assert hashlib.sha256(video.read_bytes()).hexdigest() == original_hash
    # Cached pixels cannot hide a deleted LUT.
    (data / "luts" / asset).unlink()
    with pytest.raises(LutMissingError):
        render_preview_frame(PreviewFrameRequest(video, "video", 0.5, grade, look, max_edge=320), data_dir=data)
