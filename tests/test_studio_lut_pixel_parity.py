"""Compare actual MP4 pixels to pause/scrub JPEGs using synthetic media/LUTs."""
from __future__ import annotations

import hashlib
import json
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


@pytest.mark.parametrize("suffix", ["png", "jpg"])
def test_photo_zero_strength_matches_export_source_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str,
) -> None:
    """PNG must use export's normalized photo source before YUV conversion."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg unavailable")
    data = tmp_path / "data"
    monkeypatch.setattr("orga_drone.config.settings", Settings(data_dir=data))
    photo = tmp_path / f"swatches.{suffix}"
    image = Image.new("RGB", (1280, 720))
    colors = [(180, 100, 60), (55, 120, 185), (128, 128, 128), (32, 32, 32),
              (210, 210, 210), (70, 170, 95), (180, 65, 140), (210, 180, 70)]
    for i, color in enumerate(colors):
        image.paste(color, (i % 4 * 320, i // 4 * 360, (i % 4 + 1) * 320, (i // 4 + 1) * 360))
    image.save(photo, quality=98, subsampling=0)
    original = hashlib.sha256(photo.read_bytes()).hexdigest()
    from orga_drone.studio_lut import write_identity_cube

    cube = tmp_path / "identity.cube"
    write_identity_cube(cube)
    asset = import_lut_from_path(data, cube)
    look = ColorLook(creative_lut=asset, creative_strength=0)
    output = FfmpegStudioEncoder().render(StudioExportConfig(
        output_path=tmp_path / "export.mp4", width=1280, height=720, quality="best",
        clips=(StudioExportClip(photo, "photo", 0.5, color_look=look),),
    ))
    still = render_preview_frame(PreviewFrameRequest(photo, "photo", 0, ImageAdjust(), look), data_dir=data)
    extracted = tmp_path / "export.png"
    _run(ffmpeg, "-i", str(output), "-frames:v", "1", "-vf", "scale=640:360", str(extracted))
    with Image.open(still) as a, Image.open(extracted) as b:
        difference = ImageChops.difference(a.convert("RGB").resize((640, 360)), b.convert("RGB"))
        for i in range(8):
            x, y = i % 4 * 160, i // 4 * 180
            error = sum(ImageStat.Stat(difference.crop((x + 32, y + 32, x + 128, y + 148))).mean) / 3
            assert error <= 3.0, (suffix, i, error)
    assert hashlib.sha256(photo.read_bytes()).hexdigest() == original


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
    # Stable color bars on either side of a visible timed change avoid confusing
    # adjacent CFR frame rounding with a color mismatch on moving test patterns.
    _run(ffmpeg, "-f", "lavfi", "-i",
         "smptebars=s=320x180:r=30:d=2,negate=enable='gte(t,1)'",
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
        clip = StudioExportClip(video, "video", 1.5, source_start_s=0.3,
                                source_end_s=1.8, image=grade, color_look=look)
        output = FfmpegStudioEncoder().render(StudioExportConfig(
            output_path=tmp_path / f"export-{strength}.mp4", width=320, height=180,
            clips=(clip,), quality="best",
        ))
        for local in (0.2, 1.0):
            still = render_preview_frame(PreviewFrameRequest(
                video, "video", 0.3 + local, grade, look, max_edge=320,
            ), data_dir=data)
            extracted = tmp_path / f"frame-{strength}-{local}.png"
            _run(ffmpeg, "-ss", str(local), "-i", str(output), "-frames:v", "1",
                 "-vf", "scale=in_color_matrix=bt709:in_range=tv,format=rgb24", str(extracted))
            with Image.open(still) as a, Image.open(extracted) as b:
                # JPEG + H264 chroma/scaling tolerances; dramatic LUT shifts fail.
                difference = ImageStat.Stat(ImageChops.difference(a.convert("RGB"), b.convert("RGB")))
                assert max(difference.mean) < 8, json.dumps({
                    "strength": strength, "conversion": conversion, "time": local,
                    "error": difference.mean,
                    "preview_rgb": ImageStat.Stat(a.convert("RGB")).mean,
                    "export_rgb": ImageStat.Stat(b.convert("RGB")).mean,
                    "ffmpeg": subprocess.run([ffmpeg, "-version"], capture_output=True,
                                             text=True, check=True).stdout.splitlines()[0],
                })
                if local == 0.2:
                    means.append(ImageStat.Stat(a.convert("RGB")).mean)
    assert max(abs(means[0][i] - means[2][i]) for i in range(3)) > 10
    assert means[0][1] > means[1][1] > means[2][1]
    assert hashlib.sha256(video.read_bytes()).hexdigest() == original_hash
    # Cached pixels cannot hide a deleted LUT.
    (data / "luts" / asset).unlink()
    with pytest.raises(LutMissingError):
        render_preview_frame(PreviewFrameRequest(video, "video", 0.5, grade, look, max_edge=320), data_dir=data)
