"""Reproducible local-dehaze spike for issue #302.

This is a development benchmark, not product code. It uses only Pillow and the
bundled FFmpeg (``imageio-ffmpeg``). It does not need OpenCV, NumPy, SciPy, a
network service, or any generative model.

The point is to make the discovery evidence repeatable:

- build a synthetic hazy aerial scene with a known clean reference;
- estimate one atmospheric-light colour with the dark-channel heuristic;
- compare global atmospheric-light subtraction against the existing Studio
  manual controls (contrast, highlights, detail/sharpen);
- optionally run the same comparison on local real images or video frames
  supplied by the operator. Source media is read-only and never committed;
- optionally measure encode cost for 1080p and 4K video.

Examples::

    python docs/discovery/302-local-dehaze-benchmark.py --out .dehaze-out

    python docs/discovery/302-local-dehaze-benchmark.py \
        --source "overcast hills=C:/fixtures/hills.jpg" \
        --source "sunset city=C:/fixtures/city.jpg" \
        --out .dehaze-out

    python docs/discovery/302-local-dehaze-benchmark.py \
        --timing-source "1080p=C:/fixtures/1080.mp4" \
        --timing-source "4K=C:/fixtures/4k.mp4" \
        --out .dehaze-out

The committed measurement report in ``302-local-dehaze-measurements.json`` was
produced with the same script on private local drone footage. The footage and
its original file names stay outside the repository.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

import imageio_ffmpeg

STRENGTHS = (50, 100)
DEFAULT_T_MIN = 0.85
ATMOSPHERE_CAP = 0.90
ATMOSPHERE_FLOOR = 0.35
FFMPEG_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class Levels:
    """One bounded atmospheric-light subtraction step."""

    transmission: float
    low: tuple[float, float, float]
    high: tuple[float, float, float]

    @property
    def is_neutral(self) -> bool:
        return (
            abs(self.transmission - 1.0) < 1e-9
            and max(self.low) < 1e-9
            and min(self.high) > 1.0 - 1e-9
        )


def ffmpeg_exe() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _resize_max_edge(image: Image.Image, max_edge: int) -> Image.Image:
    rgb = image.convert("RGB")
    if max(rgb.size) <= max_edge:
        return rgb
    scale = max_edge / max(rgb.size)
    size = (max(1, int(rgb.width * scale)), max(1, int(rgb.height * scale)))
    return rgb.resize(size, Image.BILINEAR)


def dark_channel(image: Image.Image) -> Image.Image:
    """Per-pixel minimum across R, G and B."""
    red, green, blue = image.convert("RGB").split()
    return ImageChops.darker(ImageChops.darker(red, green), blue)


def estimate_atmosphere(
    image: Image.Image,
    *,
    sample_edge: int = 640,
    cap: float = ATMOSPHERE_CAP,
    floor: float = ATMOSPHERE_FLOOR,
    valid_max: float = 0.97,
    percentile: float = 99.5,
) -> tuple[float, float, float]:
    """Estimate one atmospheric-light colour from the brightest dark channel.

    Near-white pixels (clouds, clipped sky, sun) are excluded because they are
    not atmospheric haze. The result is capped at ``cap``. The uncapped,
    cloud-including variant returns 1.0 on several real flights and crushes
    foreground shadows, which is why the cap exists.
    """
    small = _resize_max_edge(image, sample_edge)
    width, height = small.size
    dark = dark_channel(small).filter(ImageFilter.MinFilter(15))
    pixels = small.load()
    dark_pixels = dark.load()
    candidates: list[tuple[int, int, int, int]] = []
    for y in range(height):
        for x in range(width):
            red, green, blue = pixels[x, y]
            if max(red, green, blue) < int(255 * valid_max):
                candidates.append((dark_pixels[x, y], red, green, blue))
    if len(candidates) < 50:
        candidates = [
            (dark_pixels[x, y], *pixels[x, y])
            for y in range(height)
            for x in range(width)
        ]
    candidates.sort(key=lambda item: item[0])
    take = max(1, int(len(candidates) * (1.0 - percentile / 100.0)))
    top = candidates[-take:]
    count = len(top)
    red = sum(item[1] for item in top) / (count * 255.0)
    green = sum(item[2] for item in top) / (count * 255.0)
    blue = sum(item[3] for item in top) / (count * 255.0)
    return (
        _clamp(red, floor, cap),
        _clamp(green, floor, cap),
        _clamp(blue, floor, cap),
    )


def levels_for(
    atmosphere: Sequence[float],
    strength: int,
    t_min: float = DEFAULT_T_MIN,
) -> Levels:
    """Map a 0..100 strength to a bounded ``colorlevels`` input range.

    ``strength=0`` is identity. At full strength the transmission floor is
    ``t_min`` (0.85 by default), so the transform removes only part of the veil.
    """
    if not 0 <= int(strength) <= 100:
        raise ValueError("strength must be from 0 to 100")
    if not 0.0 < t_min <= 1.0:
        raise ValueError("t_min must be greater than 0 and at most 1")
    if len(atmosphere) != 3:
        raise ValueError("atmosphere must have three channels")
    strength_f = int(strength) / 100.0
    transmission = 1.0 - strength_f * (1.0 - t_min)
    low = []
    high = []
    for channel in atmosphere:
        value = _clamp(float(channel), 0.0, 1.0)
        lo = _clamp(value * (1.0 - transmission), 0.0, 1.0)
        hi = _clamp(lo + transmission, 0.0, 1.0)
        low.append(lo)
        high.append(hi)
    return Levels(transmission, tuple(low), tuple(high))


def _fmt(value: float) -> str:
    return f"{value:.6f}"


def ffmpeg_colorlevels(levels: Levels, saturation: float | None = None) -> str:
    """FFmpeg filter text built only from validated numbers."""
    bits: list[str] = []
    for channel, value in zip("rgb", levels.low):
        bits.append(f"{channel}imin={_fmt(value)}")
    for channel, value in zip("rgb", levels.high):
        bits.append(f"{channel}imax={_fmt(value)}")
    chain = "colorlevels=" + ":".join(bits)
    if saturation is not None:
        chain += f",eq=saturation={_fmt(float(saturation))}"
    return chain


def apply_levels(image: Image.Image, levels: Levels) -> Image.Image:
    """Apply the same per-channel linear map as FFmpeg ``colorlevels``."""
    rgb = image.convert("RGB")
    channels = []
    for channel, lo, hi in zip(rgb.split(), levels.low, levels.high):
        span = max(1e-9, hi - lo)
        lut = [
            int(round(255.0 * _clamp((value / 255.0 - lo) / span, 0.0, 1.0)))
            for value in range(256)
        ]
        channels.append(channel.point(lut))
    return Image.merge("RGB", channels)


def run_ffmpeg(src: Path, dst: Path, filter_chain: str) -> None:
    command = [
        ffmpeg_exe(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-vf",
        filter_chain,
        "-frames:v",
        "1",
        "-compression_level",
        "1",
        str(dst),
    ]
    subprocess.run(command, check=True, timeout=FFMPEG_TIMEOUT_S)


def _stat_mean(image: Image.Image) -> float:
    return ImageStat.Stat(image).mean[0]


def _stat_std(image: Image.Image) -> float:
    return ImageStat.Stat(image).stddev[0]


def _luma(image: Image.Image) -> Image.Image:
    return image.convert("L")


def psnr(reference: Image.Image, test: Image.Image) -> float:
    difference = ImageChops.difference(reference.convert("RGB"), test.convert("RGB"))
    stat = ImageStat.Stat(difference)
    mse = sum(stat.sum2) / (difference.width * difference.height * 3.0)
    if mse <= 1e-12:
        return 99.0
    return 10.0 * math.log10((255.0 * 255.0) / mse)


def ssim(reference: Image.Image, test: Image.Image, radius: int = 3) -> float:
    """Coarse local SSIM on luma using Pillow box blur."""
    first = _luma(reference)
    second = _luma(test)
    if first.size != second.size:
        second = second.resize(first.size, Image.BILINEAR)
    mu_first = first.filter(ImageFilter.BoxBlur(radius))
    mu_second = second.filter(ImageFilter.BoxBlur(radius))
    square_first = first.point(lambda value: (value * value) // 255)
    square_second = second.point(lambda value: (value * value) // 255)
    cross = ImageChops.multiply(first, second)
    sigma_first = ImageChops.subtract(
        square_first.filter(ImageFilter.BoxBlur(radius)),
        mu_first.point(lambda value: (value * value) // 255),
    )
    sigma_second = ImageChops.subtract(
        square_second.filter(ImageFilter.BoxBlur(radius)),
        mu_second.point(lambda value: (value * value) // 255),
    )
    sigma_cross = ImageChops.subtract(
        cross.filter(ImageFilter.BoxBlur(radius)),
        ImageChops.multiply(
            mu_first, mu_second
        ),
    )
    mean_first = _stat_mean(mu_first)
    mean_second = _stat_mean(mu_second)
    var_first = max(0.0, _stat_mean(sigma_first))
    var_second = max(0.0, _stat_mean(sigma_second))
    covariance = _stat_mean(sigma_cross)
    c1 = (0.01 * 255.0) ** 2
    c2 = (0.03 * 255.0) ** 2
    numerator = (2.0 * mean_first * mean_second + c1) * (2.0 * covariance + c2)
    denominator = (
        (mean_first * mean_first + mean_second * mean_second + c1)
        * (var_first + var_second + c2)
    )
    if denominator <= 1e-12:
        return 1.0
    return numerator / denominator


def gradient_mean(image: Image.Image) -> float:
    luma = _luma(image)
    horizontal = ImageChops.difference(
        luma.crop((0, 0, max(1, luma.width - 1), luma.height)),
        luma.crop((1, 0, luma.width, luma.height)),
    )
    vertical = ImageChops.difference(
        luma.crop((0, 0, luma.width, max(1, luma.height - 1))),
        luma.crop((0, 1, luma.width, luma.height)),
    )
    return (_stat_mean(horizontal) + _stat_mean(vertical)) / 2.0


def high_frequency_mean(image: Image.Image) -> float:
    luma = _luma(image)
    smoothed = luma.filter(ImageFilter.GaussianBlur(1.5))
    return _stat_mean(ImageChops.difference(luma, smoothed))


def clipping_fraction(image: Image.Image, low: int = 2, high: int = 253) -> tuple[float, float]:
    rgb = image.convert("RGB")
    total = rgb.width * rgb.height * 3
    dark = 0
    bright = 0
    for channel in rgb.split():
        histogram = channel.histogram()
        dark += sum(histogram[: low + 1])
        bright += sum(histogram[high:])
    return dark / total, bright / total


def image_metrics(image: Image.Image) -> dict[str, float]:
    luma = _luma(image)
    dark, bright = clipping_fraction(image)
    red, green, blue = image.convert("RGB").split()
    mean_red = _stat_mean(red)
    mean_blue = _stat_mean(blue)
    chroma = (
        _stat_mean(ImageChops.difference(red, luma))
        + _stat_mean(ImageChops.difference(green, luma))
        + _stat_mean(ImageChops.difference(blue, luma))
    ) / 3.0
    return {
        "mean_luma": round(_stat_mean(luma), 4),
        "std_luma": round(_stat_std(luma), 4),
        "gradient": round(gradient_mean(image), 4),
        "high_frequency": round(high_frequency_mean(image), 4),
        "clip_low": round(dark, 5),
        "clip_high": round(bright, 5),
        "mean_r_minus_b": round((mean_red - mean_blue) / 255.0, 4),
        "chroma": round(chroma / 255.0, 4),
    }


def _scene_sky(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    horizon = int(height * 0.55)
    for y in range(horizon):
        progress = y / max(1, horizon)
        red = int(86 + progress * 120)
        green = int(142 + progress * 85)
        blue = int(205 + progress * 30)
        draw.line((0, y, width, y), fill=(red, green, blue))
    draw.ellipse(
        (width * 0.66, height * 0.08, width * 0.84, height * 0.23),
        fill=(246, 248, 250),
    )


def _scene_land(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    horizon = int(height * 0.55)
    draw.polygon(
        [
            (0, horizon),
            (width * 0.18, horizon - height * 0.09),
            (width * 0.36, horizon - height * 0.04),
            (width * 0.58, horizon - height * 0.11),
            (width * 0.82, horizon - height * 0.05),
            (width, horizon - height * 0.02),
            (width, horizon),
        ],
        fill=(92, 120, 112),
    )
    draw.rectangle(
        (0, horizon, width, height * 0.68), fill=(91, 137, 156)
    )
    draw.rectangle(
        (0, height * 0.68, width, height), fill=(116, 134, 72)
    )
    for index in range(14):
        left = int(width * (index / 14.0))
        top = int(height * (0.69 + (index % 3) * 0.035))
        draw.rectangle(
            (left, top, left + int(width * 0.045), top + int(height * 0.05)),
            fill=(138, 154, 86),
        )
    draw.polygon(
        [
            (0, height * 0.93),
            (width * 0.35, height * 0.78),
            (width * 0.62, height * 0.84),
            (width, height * 0.74),
            (width, height),
            (0, height),
        ],
        fill=(54, 78, 58),
    )
    draw.line(
        (
            width * 0.05,
            height * 0.98,
            width * 0.48,
            height * 0.70,
            width * 0.72,
            height * 0.76,
        ),
        fill=(150, 143, 123),
        width=6,
    )
    for index in range(8):
        left = int(width * (0.12 + index * 0.10))
        top = int(height * (0.76 + (index % 2) * 0.03))
        draw.rectangle(
            (left, top, left + int(width * 0.035), top + int(height * 0.055)),
            fill=(196, 186, 166),
        )


def synthetic_pair(
    width: int = 640,
    height: int = 360,
    beta: float = 0.85,
    seed: int = 302,
) -> tuple[Image.Image, Image.Image]:
    """Clean aerial-like scene and its hazy counterpart."""
    clean = Image.new("RGB", (width, height), (120, 150, 160))
    draw = ImageDraw.Draw(clean)
    _scene_sky(draw, width, height)
    _scene_land(draw, width, height)
    rng = random.Random(seed)
    noise = Image.new("L", (width, height))
    noise.putdata([rng.randint(124, 131) for _ in range(width * height)])
    clean = ImageChops.add(clean, Image.merge("RGB", (noise, noise, noise)), 1.0, -128)
    clean = Image.eval(clean, lambda value: int(_clamp(value - 3, 0, 255)))

    haze = Image.new("RGB", (width, height))
    source = clean.load()
    target = haze.load()
    atmosphere = (0.82, 0.86, 0.90)
    for y in range(height):
        depth = 1.0 - (y / max(1, height - 1))
        transmission = math.exp(-beta * depth)
        for x in range(width):
            red, green, blue = source[x, y]
            target[x, y] = (
                int(red * transmission + atmosphere[0] * 255.0 * (1.0 - transmission)),
                int(green * transmission + atmosphere[1] * 255.0 * (1.0 - transmission)),
                int(blue * transmission + atmosphere[2] * 255.0 * (1.0 - transmission)),
            )
    return clean, haze


def _label_filename(label: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", label).strip("._")
    return cleaned or "frame"


def _sheet(rows: Iterable[tuple[str, Image.Image]], destination: Path) -> None:
    items = list(rows)
    if not items:
        return
    columns = 3
    thumb_width = 420
    thumbs = []
    for label, image in items:
        thumb = image.convert("RGB").copy()
        thumb.thumbnail((thumb_width, int(thumb_width * thumb.height / thumb.width)))
        thumbs.append((label, thumb))
    row_height = max(thumb.height for _, thumb in thumbs) + 24
    rows_count = (len(thumbs) + columns - 1) // columns
    canvas = Image.new(
        "RGB", (columns * thumb_width, rows_count * row_height), (16, 16, 16)
    )
    draw = ImageDraw.Draw(canvas)
    for index, (label, thumb) in enumerate(thumbs):
        x = (index % columns) * thumb_width
        y = (index // columns) * row_height
        canvas.paste(thumb, (x, y + 24))
        draw.text((x + 4, y + 5), label, fill=(255, 255, 255))
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination)


def compare_synthetic(workspace: Path, width: int, height: int) -> dict[str, object]:
    clean, hazy = synthetic_pair(width=width, height=height)
    atmosphere = estimate_atmosphere(hazy)
    source = workspace / "synthetic_hazy.png"
    clean_path = workspace / "synthetic_clean.png"
    clean.save(clean_path)
    hazy.save(source)
    rows: list[tuple[str, Image.Image]] = [("hazy input", hazy)]
    results: dict[str, object] = {
        "atmosphere": [round(value, 4) for value in atmosphere],
        "variants": {},
    }
    results["variants"]["hazy"] = {
        "psnr": round(psnr(clean, hazy), 3),
        "ssim": round(ssim(clean, hazy), 4),
        "gradient_ratio": round(gradient_mean(hazy) / max(1e-9, gradient_mean(clean)), 4),
        **image_metrics(hazy),
    }
    for strength in STRENGTHS:
        levels = levels_for(atmosphere, strength)
        variant = apply_levels(hazy, levels)
        label = f"global {strength}% (t_min {DEFAULT_T_MIN})"
        results["variants"][label] = {
            "psnr": round(psnr(clean, variant), 3),
            "ssim": round(ssim(clean, variant), 4),
            "gradient_ratio": round(
                gradient_mean(variant) / max(1e-9, gradient_mean(clean)), 4
            ),
            **image_metrics(variant),
        }
        variant.save(workspace / f"synthetic_global_{strength}.png")
        rows.append((label, variant))
        ffmpeg_destination = workspace / f"synthetic_ffmpeg_{strength}.png"
        run_ffmpeg(source, ffmpeg_destination, ffmpeg_colorlevels(levels))
        difference = ImageChops.difference(
            variant, Image.open(ffmpeg_destination).convert("RGB")
        )
        mean_difference = ImageStat.Stat(difference).mean
        results.setdefault("ffmpeg_parity", {})[str(strength)] = {
            "mean_abs_rgb": round(sum(mean_difference) / 3.0 / 255.0, 5),
            "max_channel": int(difference.getextrema()[0][1]),
        }
    manual = {
        "contrast + saturation": "eq=contrast=1.2500:saturation=1.2000",
        "contrast + highlights": (
            "eq=contrast=1.2500:saturation=1.2000,"
            "colorlevels=rimin=0:gimin=0:bimin=0:"
            "rimax=0.94:gimax=0.94:bimax=0.94"
        ),
        "detail sharpen": "unsharp=5:5:0.4000:5:5:0.0000",
        "local contrast": (
            "eq=contrast=1.2500:saturation=1.1200,"
            "unsharp=5:5:0.5000:5:5:0.0000"
        ),
    }
    for label, chain in manual.items():
        destination = workspace / f"synthetic_{_label_filename(label)}.png"
        run_ffmpeg(source, destination, chain)
        variant = Image.open(destination).convert("RGB")
        results["variants"][label] = {
            "psnr": round(psnr(clean, variant), 3),
            "ssim": round(ssim(clean, variant), 4),
            "gradient_ratio": round(
                gradient_mean(variant) / max(1e-9, gradient_mean(clean)), 4
            ),
            **image_metrics(variant),
        }
        rows.append((label, variant))
    _sheet(rows, workspace / "sheet_synthetic.png")
    return results


def _load_real_source(
    source: Path, workspace: Path, label: str
) -> list[tuple[str, Path]]:
    suffix = source.suffix.lower()
    if suffix in {".mp4", ".mov", ".m4v", ".mkv", ".avi"}:
        frames = []
        for index, fraction in enumerate((0.2, 0.5, 0.8)):
            destination = workspace / f"{_label_filename(label)}_{index}.png"
            command = [
                ffmpeg_exe(),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{fraction * 10.0:.2f}",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-vf",
                "scale='min(1920,iw)':-2",
                str(destination),
            ]
            # The probe reads the real duration first, then seeks a fraction.
            duration = _video_duration(source)
            command[command.index("-ss") + 1] = f"{duration * fraction:.2f}"
            subprocess.run(command, check=True, timeout=FFMPEG_TIMEOUT_S)
            frames.append((f"{label} @{int(fraction * 100)}%", destination))
        return frames
    return [(label, source)]


def _video_duration(source: Path) -> float:
    completed = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-i", str(source)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=FFMPEG_TIMEOUT_S,
    )
    match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", completed.stderr)
    if not match:
        return 1.0
    return (
        int(match.group(1)) * 3600
        + int(match.group(2)) * 60
        + float(match.group(3))
    )


def compare_sources(
    sources: Sequence[tuple[str, Path]], workspace: Path, max_edge: int
) -> dict[str, object]:
    report: dict[str, object] = {}
    for label, source in sources:
        resolved = source.expanduser()
        if not resolved.exists():
            raise FileNotFoundError(resolved)
        frames = _load_real_source(resolved, workspace, label)
        loaded = []
        for frame_label, frame_path in frames:
            loaded.append((frame_label, _resize_max_edge(Image.open(frame_path), max_edge)))
        atmospheres = [estimate_atmosphere(image) for _, image in loaded]
        atmosphere = tuple(
            statistics.median(values[index] for values in atmospheres)
            for index in range(3)
        )
        naive_atmospheres = [
            estimate_atmosphere(
                image,
                cap=1.0,
                floor=0.0,
                valid_max=1.01,
                percentile=99.9,
            )
            for _, image in loaded
        ]
        naive_atmosphere = tuple(
            statistics.median(values[index] for values in naive_atmospheres)
            for index in range(3)
        )
        entries: dict[str, object] = {
            "atmosphere": [round(value, 4) for value in atmosphere],
            "atmosphere_naive_uncapped": [
                round(value, 4) for value in naive_atmosphere
            ],
            "frame_atmospheres": [
                [round(value, 4) for value in values] for values in atmospheres
            ],
            "variants": {},
        }
        rows: list[tuple[str, Image.Image]] = []
        for frame_label, image in loaded:
            source_path = workspace / f"{_label_filename(frame_label)}_source.png"
            image.save(source_path)
            rows.append((f"{frame_label} / source", image))
            entries["variants"].setdefault("source", []).append(image_metrics(image))
            for strength in STRENGTHS:
                levels = levels_for(atmosphere, strength)
                variant = apply_levels(image, levels)
                entries["variants"].setdefault(
                    f"global {strength}%", []
                ).append(image_metrics(variant))
                rows.append((f"{frame_label} / global {strength}%", variant))
            naive_levels = levels_for(naive_atmosphere, 100, t_min=0.5)
            naive_variant = apply_levels(image, naive_levels)
            entries["variants"].setdefault("global naive 100%", []).append(
                image_metrics(naive_variant)
            )
            rows.append((f"{frame_label} / naive 100%", naive_variant))
            for variant_label, chain in (
                ("contrast + saturation", "eq=contrast=1.2500:saturation=1.2000"),
                ("detail sharpen", "unsharp=5:5:0.4000:5:5:0.0000"),
            ):
                destination = (
                    workspace / f"{_label_filename(frame_label)}_{_label_filename(variant_label)}.png"
                )
                run_ffmpeg(source_path, destination, chain)
                variant = Image.open(destination).convert("RGB")
                entries["variants"].setdefault(variant_label, []).append(
                    image_metrics(variant)
                )
                rows.append((f"{frame_label} / {variant_label}", variant))
        report[label] = entries
        _sheet(rows, workspace / f"sheet_{_label_filename(label)}.png")
    return report


def measure_timing(
    sources: Sequence[tuple[str, Path]], runs: int, seconds: float
) -> dict[str, object]:
    atmosphere = (0.90, 0.90, 0.90)
    levels = levels_for(atmosphere, 100)
    chains = {
        "none": None,
        "dehaze": ffmpeg_colorlevels(levels),
        "dehaze + saturation": ffmpeg_colorlevels(levels, saturation=1.04),
        "contrast + saturation": "eq=contrast=1.2500:saturation=1.2000",
        "dehaze + saturation + sharpen": (
            ffmpeg_colorlevels(levels, saturation=1.04)
            + ",unsharp=5:5:0.4000:5:5:0.0000"
        ),
    }
    report: dict[str, object] = {}
    for label, source in sources:
        resolved = source.expanduser()
        if not resolved.exists():
            raise FileNotFoundError(resolved)
        report[label] = {}
        for chain_label, chain in chains.items():
            timings = []
            for _ in range(max(1, runs)):
                command = [
                    ffmpeg_exe(),
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    "1",
                    "-i",
                    str(resolved),
                    "-t",
                    f"{seconds:.3f}",
                    "-an",
                ]
                if chain is not None:
                    command += ["-vf", chain]
                command += [
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-crf",
                    "23",
                    "-f",
                    "null",
                    "-",
                ]
                started = time.perf_counter()
                subprocess.run(command, check=True, timeout=FFMPEG_TIMEOUT_S)
                timings.append(round(time.perf_counter() - started, 3))
            report[label][chain_label] = {
                "median_s": round(statistics.median(timings), 3),
                "runs": timings,
            }
    return report


def _parse_sources(values: Sequence[str] | None) -> list[tuple[str, Path]]:
    parsed: list[tuple[str, Path]] = []
    for value in values or []:
        if "=" not in value:
            raise ValueError("use LABEL=PATH for --source")
        label, path = value.split("=", 1)
        parsed.append((label.strip(), Path(path.strip())))
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="dehaze-spike-out", help="output directory")
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="real image or video as LABEL=PATH (repeatable, never copied to the repo)",
    )
    parser.add_argument(
        "--timing-source",
        action="append",
        default=[],
        help="video for encode timing as LABEL=PATH (repeatable)",
    )
    parser.add_argument("--timing", action="store_true", help="run encode timing")
    parser.add_argument("--timing-runs", type=int, default=3)
    parser.add_argument("--timing-seconds", type=float, default=1.0)
    parser.add_argument("--max-edge", type=int, default=1280)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    parser.add_argument(
        "--skip-synthetic", action="store_true", help="only run --source/--timing"
    )
    args = parser.parse_args(argv)

    workspace = Path(args.out).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "script": Path(__file__).name,
        "t_min": DEFAULT_T_MIN,
        "atmosphere_cap": ATMOSPHERE_CAP,
        "note": "no OpenCV; source media stays outside the repository",
    }
    if not args.skip_synthetic:
        report["synthetic"] = compare_synthetic(
            workspace, max(64, args.width), max(36, args.height)
        )
    sources = _parse_sources(args.source)
    if sources:
        report["sources"] = compare_sources(sources, workspace, max(160, args.max_edge))
    timing_sources = _parse_sources(args.timing_source)
    if args.timing and timing_sources:
        report["timing"] = measure_timing(
            timing_sources, args.timing_runs, args.timing_seconds
        )
    destination = workspace / "measurements.json"
    destination.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(destination)
    print(json.dumps(report.get("synthetic", {}).get("variants", {}), indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # pragma: no cover - CLI guard
        print(f"dehaze benchmark failed: {error}", file=sys.stderr)
        raise
