"""Focused checks for the local-dehaze discovery benchmark (#302).

The benchmark is a development artefact, not product code. These tests keep its
core maths deterministic and make the documented failure modes explicit.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from PIL import Image, ImageDraw

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "discovery"
    / "302-local-dehaze-benchmark.py"
)
SPEC = importlib.util.spec_from_file_location("dehaze_benchmark_302", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
dehaze = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dehaze
SPEC.loader.exec_module(dehaze)


def _gradient(width: int = 64, height: int = 48) -> Image.Image:
    image = Image.new("RGB", (width, height))
    pixels = []
    for y in range(height):
        for x in range(width):
            value = int(255 * (x + y) / max(1, width + height - 2))
            pixels.append((value, max(0, value - 20), max(0, value - 40)))
    image.putdata(pixels)
    return image


def test_neutral_levels_are_identity() -> None:
    image = _gradient()
    levels = dehaze.levels_for((0.9, 0.9, 0.9), 0)
    assert levels.is_neutral
    result = dehaze.apply_levels(image, levels)
    assert result.tobytes() == image.tobytes()


def test_estimator_caps_bright_clouds() -> None:
    image = Image.new("RGB", (160, 120), (120, 130, 140))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 160, 50), fill=(255, 255, 255))
    robust = dehaze.estimate_atmosphere(image)
    assert all(channel <= dehaze.ATMOSPHERE_CAP for channel in robust)
    assert max(robust) < 0.96


def test_naive_estimator_can_return_white_on_clouds() -> None:
    image = Image.new("RGB", (160, 120), (60, 70, 80))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 160, 80), fill=(255, 255, 255))
    naive = dehaze.estimate_atmosphere(
        image,
        cap=1.0,
        floor=0.0,
        valid_max=1.01,
        percentile=99.9,
    )
    assert min(naive) > 0.95


def test_synthetic_haze_improves_with_bounded_global_transform() -> None:
    clean, hazy = dehaze.synthetic_pair(width=96, height=64)
    atmosphere = dehaze.estimate_atmosphere(hazy)
    levels = dehaze.levels_for(atmosphere, 100)
    dehazed = dehaze.apply_levels(hazy, levels)
    assert dehaze.psnr(clean, dehazed) > dehaze.psnr(clean, hazy)
    assert dehaze.ssim(clean, dehazed) >= dehaze.ssim(clean, hazy)


def test_ffmpeg_colorlevels_matches_pillow(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    destination = tmp_path / "ffmpeg.png"
    image = _gradient()
    image.save(source)
    levels = dehaze.levels_for((0.86, 0.88, 0.90), 100)
    dehaze.run_ffmpeg(source, destination, dehaze.ffmpeg_colorlevels(levels))
    expected = dehaze.apply_levels(image, levels)
    actual = Image.open(destination).convert("RGB")
    difference = dehaze.ImageChops.difference(expected, actual)
    mean_error = sum(dehaze.ImageStat.Stat(difference).mean) / 3.0
    assert mean_error < 2.0


def test_filter_text_uses_only_validated_numbers() -> None:
    levels = dehaze.levels_for((0.86, 0.88, 0.90), 75)
    chain = dehaze.ffmpeg_colorlevels(levels, saturation=1.04)
    assert "'" not in chain
    assert ";" not in chain
    assert " " not in chain
    assert chain.startswith("colorlevels=")
    assert chain.endswith("eq=saturation=1.040000")


def test_synthetic_fixture_is_deterministic() -> None:
    first_clean, first_hazy = dehaze.synthetic_pair(width=48, height=32)
    second_clean, second_hazy = dehaze.synthetic_pair(width=48, height=32)
    assert first_clean.tobytes() == second_clean.tobytes()
    assert first_hazy.tobytes() == second_hazy.tobytes()


def test_full_strength_on_dark_scene_raises_near_black_share() -> None:
    """Document the validation failure mode: global dehaze crushes dark scenes."""
    image = Image.new("RGB", (96, 64), (28, 32, 40))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 40, 40), fill=(18, 20, 24))
    draw.rectangle((50, 8, 90, 28), fill=(220, 230, 240))
    atmosphere = dehaze.estimate_atmosphere(image)
    levels = dehaze.levels_for(atmosphere, 100)
    result = dehaze.apply_levels(image, levels)
    source_pixels = image.load()
    result_pixels = result.load()
    width, height = image.size
    total = width * height
    source_dark = sum(
        1 for y in range(height) for x in range(width) if max(source_pixels[x, y]) < 8
    ) / total
    result_dark = sum(
        1 for y in range(height) for x in range(width) if max(result_pixels[x, y]) < 8
    ) / total
    assert result_dark > source_dark
    assert result_dark > 0.05



def _near_black_share(image: Image.Image, threshold: int = 8) -> float:
    pixels = image.convert("RGB").load()
    width, height = image.size
    total = width * height
    return sum(
        1 for y in range(height) for x in range(width) if max(pixels[x, y]) < threshold
    ) / total


def test_shadow_protect_reduces_dark_scene_crush() -> None:
    """Luma-gated blend softens crush but is not a shipping Dehaze operator."""
    image = Image.new("RGB", (96, 64), (28, 32, 40))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 40, 40), fill=(18, 20, 24))
    draw.rectangle((50, 8, 90, 28), fill=(220, 230, 240))
    atmosphere = dehaze.estimate_atmosphere(image)
    levels = dehaze.levels_for(atmosphere, 100)
    crushed = dehaze.apply_levels(image, levels)
    protected = dehaze.apply_levels_shadow_protect(image, levels, protect=0.65)
    assert _near_black_share(protected) < _near_black_share(crushed)
    # Still not identity: some darkening remains, so a misleading "safe" slider
    # would still alter clear/dark scenes without a scene gate.
    assert _near_black_share(protected) >= _near_black_share(image)


def test_shadow_protect_neutral_strength_is_identity() -> None:
    image = Image.new("RGB", (32, 24), (90, 100, 110))
    levels = dehaze.levels_for((0.8, 0.8, 0.8), 0)
    result = dehaze.apply_levels_shadow_protect(image, levels, protect=0.8)
    assert result.tobytes() == image.tobytes()
