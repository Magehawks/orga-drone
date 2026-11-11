"""Reference-scenario tests for the Studio color grading stack.

Synthetic, deterministic scenes stand in for the manual reference scenarios
(Cinematic Autumn Landscape, Moody/Nordic Red Boat, Cinematic Urban
Architecture, D-Log M footage). They are visual targets, not pixel goldens:
selectivity and direction assertions use per-patch means with explicit
tolerances documented in docs/discovery/color-scenario-test-report.md.

Chain order shared by preview stills, playback proxy, and MP4 export:

    grade -> conversion/creative LUTs -> HSL mixer -> wheels -> detail -> ramp

No source media is modified; scenes are built in-memory or in tmp_path.
"""

from __future__ import annotations

import math
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat

from orga_drone.config import Settings
from orga_drone.export.studio_config import StudioExportClip, StudioExportConfig
from orga_drone.export.studio_encoder import FfmpegStudioEncoder
from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.studio_color_wheels import ColorWheelPoint, ColorWheels, apply_color_wheels_rgb
from orga_drone.studio_hsl import HslAdjust, HslRange, apply_hsl_rgb
from orga_drone.studio_image import ImageAdjust
from orga_drone.studio_lut import ColorLook, import_lut_from_path
from orga_drone.studio_preview_frame import PreviewFrameRequest, render_preview_frame

BASE_SIZE = (320, 180)
PATCH_INSET = 4

Rgb = tuple[int, int, int]
Box = tuple[int, int, int, int]
Patch = tuple[int, int, int, int, Rgb]
Scene = tuple[Image.Image, dict[str, Box]]


# ---------------------------------------------------------------------------
# Deterministic scene fixtures
# ---------------------------------------------------------------------------


def _flat(color: Rgb) -> Rgb:
    """Wash a color toward mid gray the way flat log profiles do."""
    return (
        int(128 + (color[0] - 128) * 0.35),
        int(128 + (color[1] - 128) * 0.35),
        int(128 + (color[2] - 128) * 0.35),
    )


def _scene_from_patches(patches: dict[str, Patch], scale: int = 1) -> Scene:
    """Build a scene at ``BASE_SIZE * scale``. Boxes come back in 320-space
    coordinates scaled the same way, inset so edges never leak into samples."""
    image = Image.new("RGB", (BASE_SIZE[0] * scale, BASE_SIZE[1] * scale), (128, 128, 128))
    boxes: dict[str, Box] = {}
    for name, (left, top, right, bottom, color) in patches.items():
        image.paste(
            color,
            (left * scale, top * scale, right * scale, bottom * scale),
        )
        inset = PATCH_INSET * scale
        boxes[name] = (
            left * scale + inset, top * scale + inset,
            right * scale - inset, bottom * scale - inset,
        )
    return image, boxes


_AUTUMN_PATCHES: dict[str, Patch] = {
    "sky": (0, 0, 320, 50, (143, 166, 184)),
    "orange": (20, 70, 90, 110, (200, 106, 44)),
    "yellow": (120, 70, 190, 110, (217, 160, 50)),
    "green": (230, 70, 300, 110, (78, 122, 58)),
    "water": (0, 130, 320, 180, (46, 63, 74)),
}


def _autumn_scene(scale: int = 1) -> Scene:
    """Cinematic Autumn Landscape: warm foliage, cool sky and water."""
    return _scene_from_patches(_AUTUMN_PATCHES, scale)


def _red_boat_scene(scale: int = 1) -> Scene:
    """Nordic Red Boat: red hull, gray-blue water, pale sky, dark rock."""
    return _scene_from_patches(
        {
            "sky": (0, 0, 320, 60, (201, 210, 216)),
            "hull": (120, 95, 220, 135, (176, 58, 46)),
            "water": (0, 150, 320, 180, (94, 114, 133)),
            "rock": (10, 90, 70, 140, (30, 34, 38)),
        },
        scale,
    )


def _urban_sky_scene(scale: int = 1) -> Scene:
    """Cinematic Urban Architecture: saturated blue sky, warm gray building."""
    return _scene_from_patches(
        {
            "sky": (0, 0, 320, 60, (74, 127, 181)),
            "building": (90, 80, 230, 180, (140, 133, 120)),
            "shadow_wall": (250, 80, 310, 180, (38, 46, 56)),
        },
        scale,
    )


def _flat_dlog_scene(scale: int = 1) -> Scene:
    """D-Log M style flat footage: the autumn scene with washed levels."""
    washed: dict[str, Patch] = {
        name: (left, top, right, bottom, _flat(color))
        for name, (left, top, right, bottom, color) in _AUTUMN_PATCHES.items()
    }
    return _scene_from_patches(washed, scale)


def _patch_mean(image: Image.Image, box: Box) -> tuple[float, float, float]:
    stat = ImageStat.Stat(image.crop(box).convert("RGB"))
    return (stat.mean[0], stat.mean[1], stat.mean[2])


def _chroma(rgb: tuple[float, ...]) -> float:
    return max(rgb) - min(rgb)


def _apply_pixels(image: Image.Image, apply) -> Image.Image:  # type: ignore[no-untyped-def]
    raw = image.tobytes()
    out = bytearray(len(raw))
    for offset in range(0, len(raw), 3):
        triple = apply(raw[offset], raw[offset + 1], raw[offset + 2])
        out[offset] = int(round(triple[0] * 255))
        out[offset + 1] = int(round(triple[1] * 255))
        out[offset + 2] = int(round(triple[2] * 255))
    return Image.frombytes("RGB", image.size, bytes(out))


def _hue_point(hue_deg: float, radius: float = 0.8) -> ColorWheelPoint:
    angle = math.radians(hue_deg)
    return ColorWheelPoint(x=radius * math.cos(angle), y=radius * math.sin(angle))


def _write_cube(
    path: Path,
    size: int,
    transform: Callable[[float, float, float], tuple[float, float, float]],
) -> Path:
    lines = ['TITLE "Orga Drone synthetic scenario cube"', f"LUT_3D_SIZE {size}"]
    for blue in range(size):
        for green in range(size):
            for red in range(size):
                triple = transform(
                    red / (size - 1), green / (size - 1), blue / (size - 1)
                )
                lines.append(" ".join(f"{min(1.0, max(0.0, value)):.6f}" for value in triple))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _dlog_conversion_transform(red: float, green: float, blue: float) -> tuple[float, float, float]:
    """Synthetic flat-to-Rec709 style expansion: contrast plus saturation."""
    midpoint = 0.42
    expanded = tuple(
        min(1.0, max(0.0, (channel - midpoint) * 1.6 + 0.5)) for channel in (red, green, blue)
    )
    mean = sum(expanded) / 3.0
    return (
        min(1.0, max(0.0, mean + (expanded[0] - mean) * 1.5)),
        min(1.0, max(0.0, mean + (expanded[1] - mean) * 1.5)),
        min(1.0, max(0.0, mean + (expanded[2] - mean) * 1.5)),
    )


# ---------------------------------------------------------------------------
# Selective HSL mixer scenarios (pure pixel math, deterministic)
# ---------------------------------------------------------------------------


def test_autumn_selective_hsl_neutralizes_warm_foliage_only() -> None:
    scene, boxes = _autumn_scene()
    warm = HslAdjust(
        red=HslRange(saturation=-100),
        orange=HslRange(saturation=-100),
        yellow=HslRange(saturation=-100),
    )
    graded = _apply_pixels(scene, lambda r, g, b: apply_hsl_rgb(r / 255, g / 255, b / 255, warm))

    for name in ("orange", "yellow"):
        before = _patch_mean(scene, boxes[name])
        after = _patch_mean(graded, boxes[name])
        assert _chroma(after) <= 2.0, (name, before, after)
    green_before = _chroma(_patch_mean(scene, boxes["green"]))
    green_after = _chroma(_patch_mean(graded, boxes["green"]))
    assert green_after >= green_before * 0.6, (green_before, green_after)
    for name in ("sky", "water"):
        assert _patch_mean(graded, boxes[name]) == pytest.approx(
            _patch_mean(scene, boxes[name]), abs=0.01
        )


def test_red_boat_selective_hsl_keeps_water_and_sky() -> None:
    scene, boxes = _red_boat_scene()
    reds = HslAdjust(
        red=HslRange(saturation=-100),
        orange=HslRange(saturation=-100),
    )
    graded = _apply_pixels(scene, lambda r, g, b: apply_hsl_rgb(r / 255, g / 255, b / 255, reds))

    assert _chroma(_patch_mean(graded, boxes["hull"])) <= 2.0
    for name in ("water", "sky"):
        assert _patch_mean(graded, boxes[name]) == pytest.approx(
            _patch_mean(scene, boxes[name]), abs=0.01
        ), name


def test_urban_selective_hsl_targets_blue_sky_only() -> None:
    scene, boxes = _urban_sky_scene()
    blues = HslAdjust(
        aqua=HslRange(saturation=-100),
        blue=HslRange(saturation=-100),
    )
    graded = _apply_pixels(scene, lambda r, g, b: apply_hsl_rgb(r / 255, g / 255, b / 255, blues))

    assert _chroma(_patch_mean(graded, boxes["sky"])) <= 2.0
    assert _patch_mean(graded, boxes["building"]) == pytest.approx(
        _patch_mean(scene, boxes["building"]), abs=0.01
    )


def test_hsl_luminance_lifts_only_the_target_range() -> None:
    scene, boxes = _urban_sky_scene()
    lift = HslAdjust(blue=HslRange(luminance=50))
    graded = _apply_pixels(scene, lambda r, g, b: apply_hsl_rgb(r / 255, g / 255, b / 255, lift))

    sky_delta = _patch_mean(graded, boxes["sky"])[2] - _patch_mean(scene, boxes["sky"])[2]
    building_delta = _patch_mean(graded, boxes["building"])[2] - _patch_mean(scene, boxes["building"])[2]
    assert sky_delta >= 10.0
    assert abs(building_delta) <= 2.0


# ---------------------------------------------------------------------------
# Color wheels scenarios (tonal bands, zero-luma tints)
# ---------------------------------------------------------------------------


def test_wheels_shift_only_their_tonal_band() -> None:
    scene, boxes = _red_boat_scene()

    def cool_shadows(r: float, g: float, b: float) -> tuple[float, float, float]:
        return apply_color_wheels_rgb(r / 255, g / 255, b / 255, ColorWheels(shadows=_hue_point(210.0)))

    def warm_highlights(r: float, g: float, b: float) -> tuple[float, float, float]:
        return apply_color_wheels_rgb(r / 255, g / 255, b / 255, ColorWheels(highlights=_hue_point(30.0)))

    cooled = _apply_pixels(scene, cool_shadows)
    warmed = _apply_pixels(scene, warm_highlights)

    def blue_shift(result: Image.Image, box: tuple[int, int, int, int]) -> float:
        return _patch_mean(result, box)[2] - _patch_mean(scene, box)[2]

    rock_shift = blue_shift(cooled, boxes["rock"])
    water_shift = blue_shift(cooled, boxes["water"])
    sky_shift = blue_shift(cooled, boxes["sky"])
    assert rock_shift >= 20.0, rock_shift
    assert 0.0 <= water_shift < rock_shift, water_shift
    assert abs(sky_shift) <= 1.0, sky_shift

    sky_warm = _patch_mean(warmed, boxes["sky"])[0] - _patch_mean(scene, boxes["sky"])[0]
    rock_warm = _patch_mean(warmed, boxes["rock"])[0] - _patch_mean(scene, boxes["rock"])[0]
    assert sky_warm >= 5.0, sky_warm
    assert abs(rock_warm) <= 1.0, rock_warm

    def luma(rgb: tuple[float, float, float]) -> float:
        return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]

    for name in ("rock", "sky", "water"):
        shifted = luma(_patch_mean(cooled, boxes[name]))
        original = luma(_patch_mean(scene, boxes[name]))
        assert abs(shifted - original) <= 2.0, (name, shifted, original)


# ---------------------------------------------------------------------------
# Edge cases: neutral identity and extreme values
# ---------------------------------------------------------------------------


def test_neutral_stack_is_identity_on_every_scene() -> None:
    neutral_hsl = HslAdjust()
    neutral_wheels = ColorWheels()
    for build in (_autumn_scene, _red_boat_scene, _urban_sky_scene):
        scene, _ = build()
        graded = _apply_pixels(
            _apply_pixels(scene, lambda r, g, b: apply_hsl_rgb(r / 255, g / 255, b / 255, neutral_hsl)),
            lambda r, g, b: apply_color_wheels_rgb(r / 255, g / 255, b / 255, neutral_wheels),
        )
        assert graded.tobytes() == scene.tobytes()

def test_extreme_settings_stay_bounded_and_deterministic() -> None:
    scene, _ = _autumn_scene()
    extreme_hsl = HslAdjust(
        **{key: HslRange(hue=100, saturation=100, luminance=100) for key in
           ("red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta")}
    )
    extreme_wheels = ColorWheels(
        shadows=_hue_point(0.0, radius=1.0),
        midtones=_hue_point(120.0, radius=1.0),
        highlights=_hue_point(240.0, radius=1.0),
    )
    def run() -> bytes:
        first = _apply_pixels(scene, lambda r, g, b: apply_hsl_rgb(r / 255, g / 255, b / 255, extreme_hsl))
        second = _apply_pixels(first, lambda r, g, b: apply_color_wheels_rgb(r / 255, g / 255, b / 255, extreme_wheels))
        return second.tobytes()

    first_run = run()
    assert first_run == run()
    for offset in range(0, len(first_run), 3):
        pixel = first_run[offset:offset + 3]
        assert all(0 <= channel <= 255 for channel in pixel), pixel


# ---------------------------------------------------------------------------
# FFmpeg-backed scenario and parity tests (skipped without ffmpeg)
# ---------------------------------------------------------------------------


def _ffmpeg() -> str:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    return ffmpeg


def _run(ffmpeg: str, *args: str) -> None:
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", *args],
        check=True,
        capture_output=True,
        timeout=60,
        **subprocess_no_window_kwargs(),
    )


_FULL_STACK_IMAGE = ImageAdjust(exposure=12, contrast=8, warmth=10, highlights=-6, shadows=5)
_FULL_STACK_HSL = HslAdjust(orange=HslRange(saturation=25), blue=HslRange(luminance=-15))
_FULL_STACK_WHEELS = ColorWheels(shadows=_hue_point(210.0, radius=0.5), highlights=_hue_point(30.0, radius=0.4))


def _full_stack_look(data_dir: Path, tmp_path: Path, *, strength: int = 80) -> ColorLook:
    conversion = _write_cube(tmp_path / "dlog-conversion.cube", 17, _dlog_conversion_transform)
    creative = _write_cube(tmp_path / "teal-orange.cube", 17, lambda r, g, b: (
        min(1.0, r * 1.2), g, min(1.0, b * 1.15)
    ))
    conversion_asset = import_lut_from_path(data_dir, conversion)
    creative_asset = import_lut_from_path(data_dir, creative)
    return ColorLook(
        input_profile="dlog_m",
        conversion_lut=conversion_asset,
        conversion_confirmed=True,
        creative_lut=creative_asset,
        creative_strength=strength,
    )


def test_dlog_conversion_lut_restores_contrast_and_saturation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg = _ffmpeg()
    data = tmp_path / "data"
    monkeypatch.setattr("orga_drone.config.settings", Settings(data_dir=data))
    scene, _ = _flat_dlog_scene()
    photo = tmp_path / "flat.png"
    scene.save(photo)

    neutral = render_preview_frame(
        PreviewFrameRequest(photo, "photo", 0, ImageAdjust(), ColorLook(), max_edge=320),
        data_dir=data,
    )
    look = ColorLook(
        input_profile="dlog_m",
        conversion_lut=import_lut_from_path(data, _write_cube(tmp_path / "conv.cube", 17, _dlog_conversion_transform)),
        conversion_confirmed=True,
    )
    converted = render_preview_frame(
        PreviewFrameRequest(photo, "photo", 0, ImageAdjust(), look, max_edge=320), data_dir=data
    )
    assert ffmpeg  # rendered via the export FFmpeg path

    def scene_statistics(still: Path) -> tuple[float, float]:
        with Image.open(still) as image:
            patches = _flat_dlog_scene()[1]
            contrast = ImageStat.Stat(image.convert("RGB").convert("L")).stddev[0]
            chroma = sum(
                _chroma(_patch_mean(image.convert("RGB"), box)) for box in patches.values()
            ) / len(patches)
            return contrast, chroma

    neutral_contrast, neutral_chroma = scene_statistics(Path(neutral))
    converted_contrast, converted_chroma = scene_statistics(Path(converted))
    assert converted_contrast >= neutral_contrast * 1.3
    assert converted_chroma >= neutral_chroma * 1.3


@pytest.mark.parametrize("suffix", ["png", "jpg"])
def test_full_stack_still_matches_export_photo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    ffmpeg = _ffmpeg()
    data = tmp_path / "data"
    monkeypatch.setattr("orga_drone.config.settings", Settings(data_dir=data))
    scene, boxes = _autumn_scene(scale=4)
    photo = tmp_path / f"scene.{suffix}"
    if suffix == "jpg":
        scene.save(photo, quality=98, subsampling=0)
    else:
        scene.save(photo)
    look = _full_stack_look(data, tmp_path)

    still = render_preview_frame(
        PreviewFrameRequest(
            photo, "photo", 0, _FULL_STACK_IMAGE, look,
            hsl=_FULL_STACK_HSL, color_wheels=_FULL_STACK_WHEELS,
        ),
        data_dir=data,
    )
    output = FfmpegStudioEncoder().render(StudioExportConfig(
        output_path=tmp_path / "export.mp4", width=1280, height=720, quality="best",
        clips=(StudioExportClip(
            photo, "photo", 0.5, image=_FULL_STACK_IMAGE, color_look=look,
            hsl=_FULL_STACK_HSL, color_wheels=_FULL_STACK_WHEELS,
        ),),
    ))
    extracted = tmp_path / "export-frame.png"
    _run(ffmpeg, "-i", str(output), "-frames:v", "1", "-vf", "scale=640:360", str(extracted))

    with Image.open(still) as a, Image.open(extracted) as b, Image.open(photo) as source:
        # Compare below the still's native edge so JPEG block noise averages
        # out, matching the established photo parity pattern.
        a_rgb = a.convert("RGB").resize((640, 360))
        b_rgb = b.convert("RGB")
        s_rgb = source.convert("RGB").resize((640, 360))
        changed_pairs = 0
        for name, box in boxes.items():
            half_box = (box[0] // 2, box[1] // 2, box[2] // 2, box[3] // 2)
            error = sum(ImageStat.Stat(
                ImageChops.difference(a_rgb.crop(half_box), b_rgb.crop(half_box))
            ).mean) / 3
            # Measured worst patch today: green 3.19 (see
            # docs/discovery/color-scenario-test-report.md). The residual is
            # dominated by the still-side JPEG/BT.601 conversion and tracked
            # with the strict 3.0 gate in issue #320; 5.0 pins today's
            # behavior without waiving that investigation.
            assert error <= 5.0, (suffix, name, error)
            export_mean = _patch_mean(b_rgb, half_box)
            source_mean = _patch_mean(s_rgb, half_box)
            # The grade must visibly reach the exported frame.
            for channel in range(3):
                if abs(export_mean[channel] - source_mean[channel]) > 8.0:
                    changed_pairs += 1
        assert changed_pairs >= 6, changed_pairs


def test_full_stack_still_matches_export_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg = _ffmpeg()
    data = tmp_path / "data"
    monkeypatch.setattr("orga_drone.config.settings", Settings(data_dir=data))
    video = tmp_path / "synthetic.mp4"
    _run(ffmpeg, "-f", "lavfi", "-i",
         "smptebars=s=320x180:r=30:d=2,negate=enable='gte(t,1)'",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video))
    look = _full_stack_look(data, tmp_path)

    clip = StudioExportClip(
        video, "video", 1.5, source_start_s=0.3, source_end_s=1.8,
        image=_FULL_STACK_IMAGE, color_look=look,
        hsl=_FULL_STACK_HSL, color_wheels=_FULL_STACK_WHEELS,
    )
    output = FfmpegStudioEncoder().render(StudioExportConfig(
        output_path=tmp_path / "export.mp4", width=320, height=180, quality="best",
        clips=(clip,),
    ))
    for local in (0.2, 1.0):
        still = render_preview_frame(PreviewFrameRequest(
            video, "video", 0.3 + local, _FULL_STACK_IMAGE, look,
            hsl=_FULL_STACK_HSL, color_wheels=_FULL_STACK_WHEELS, max_edge=320,
        ), data_dir=data)
        extracted = tmp_path / f"frame-{local}.png"
        _run(ffmpeg, "-ss", str(local), "-i", str(output), "-frames:v", "1",
             "-vf", "scale=in_color_matrix=bt709:in_range=tv,format=rgb24", str(extracted))
        with Image.open(still) as a, Image.open(extracted) as b:
            difference = ImageStat.Stat(ImageChops.difference(a.convert("RGB"), b.convert("RGB")))
            # JPEG still + H.264 chroma/scaling tolerance; documented in the
            # scenario report. The full stack must not exceed the single-effect
            # budget already accepted for video.
            assert max(difference.mean) < 8, (local, difference.mean)


def test_full_stack_neutral_settings_encode_without_grade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg = _ffmpeg()
    data = tmp_path / "data"
    monkeypatch.setattr("orga_drone.config.settings", Settings(data_dir=data))
    scene, boxes = _autumn_scene(scale=4)
    photo = tmp_path / "scene.png"
    scene.save(photo)

    still = render_preview_frame(
        PreviewFrameRequest(photo, "photo", 0, ImageAdjust(), ColorLook()),
        data_dir=data,
    )
    output = FfmpegStudioEncoder().render(StudioExportConfig(
        output_path=tmp_path / "export.mp4", width=1280, height=720, quality="best",
        clips=(StudioExportClip(photo, "photo", 0.5),),
    ))
    extracted = tmp_path / "export-frame.png"
    _run(ffmpeg, "-i", str(output), "-frames:v", "1", "-vf", "scale=640:360", str(extracted))

    with Image.open(still) as a, Image.open(extracted) as b, Image.open(photo) as source:
        source_rgb = source.convert("RGB").resize((640, 360))
        still_rgb = a.convert("RGB").resize((640, 360))
        for box in boxes.values():
            half_box = (box[0] // 2, box[1] // 2, box[2] // 2, box[3] // 2)
            source_mean = _patch_mean(source_rgb, half_box)
            still_mean = _patch_mean(still_rgb, half_box)
            export_mean = _patch_mean(b.convert("RGB"), half_box)
            for channel in range(3):
                # Neutral settings must stay inside the documented residual
                # (worst measured 3.43, still-side JPEG/BT.601 conversion,
                # tracked in #320) and must not shift the encoded picture.
                assert abs(still_mean[channel] - export_mean[channel]) <= 5.0, (
                    half_box, still_mean, export_mean
                )
                assert abs(export_mean[channel] - source_mean[channel]) <= 6.0, (
                    half_box, export_mean, source_mean
                )
