"""Primaries-v1 arithmetic for issue #353.

Kelvin/tint and blacks/shadows/highlights/whites mappings are versioned below.
This module does not write grades and does not change the legacy exposure or
warmth path.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from orga_drone.studio_image import blackbody_channel_gains

LUMA_WEIGHTS = (0.2126, 0.7152, 0.0722)
Rgb = tuple[float, float, float]
Curve = Sequence[tuple[float, float]]

# Published UI→engine mappings. Changing them requires a new version id and
# golden vectors; the frontend must not invent a parallel approximation.
KELVIN_TINT_MAPPING = "kelvin-tint-v1"
TONE_CONTROLS_MAPPING = "tone-controls-v1"
NEUTRAL_KELVIN = 6500.0
MIN_KELVIN = 2000.0
MAX_KELVIN = 15000.0
MIN_TINT = -100.0
MAX_TINT = 100.0
TONE_SLIDER_MIN = -100.0
TONE_SLIDER_MAX = 100.0
TINT_GREEN_WEIGHT = 0.5
TINT_MAGENTA_WEIGHT = 0.25


class PrimariesError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def linear_luma(rgb: Rgb) -> float:
    return LUMA_WEIGHTS[0] * rgb[0] + LUMA_WEIGHTS[1] * rgb[1] + LUMA_WEIGHTS[2] * rgb[2]


def primaries_exposure(rgb: Rgb, stops: float) -> Rgb:
    if not -10.0 <= stops <= 10.0:
        raise PrimariesError("exposure is outside -10 to 10 stops", code="RANGE")
    factor = 2.0**stops
    return (rgb[0] * factor, rgb[1] * factor, rgb[2] * factor)


def primaries_balance(rgb: Rgb, gains: Rgb) -> Rgb:
    if not all(0.01 <= gain <= 100.0 for gain in gains):
        raise PrimariesError("balance gains are outside 0.01 to 100", code="RANGE")
    weighted = sum(LUMA_WEIGHTS[index] * gains[index] for index in range(3))
    scale = 1.0 / weighted
    return (
        gains[0] * scale * rgb[0],
        gains[1] * scale * rgb[1],
        gains[2] * scale * rgb[2],
    )


def primaries_contrast(rgb: Rgb, amount: float, pivot: float) -> Rgb:
    if not 0.0 <= amount <= 4.0:
        raise PrimariesError("contrast is outside 0 to 4", code="RANGE")
    if not 0.001 <= pivot <= 1.0:
        raise PrimariesError("contrast pivot is outside 0.001 to 1", code="RANGE")
    channels: list[float] = []
    for channel in rgb:
        if amount == 0.0:
            channels.append(math.copysign(pivot, channel) if channel != 0.0 else 0.0)
            continue
        ratio = channel / pivot
        channels.append(pivot * math.copysign(abs(ratio) ** amount, ratio))
    return (channels[0], channels[1], channels[2])


def piecewise_linear(points: Curve, position: float) -> float:
    if len(points) < 1:
        raise PrimariesError("a tone curve needs at least one point", code="CURVE")
    if any(points[index][0] >= points[index + 1][0] for index in range(len(points) - 1)):
        raise PrimariesError("tone curve x values must increase", code="CURVE")
    if any(points[index][1] > points[index + 1][1] for index in range(len(points) - 1)):
        raise PrimariesError("tone curve must be monotone", code="CURVE")
    if position <= points[0][0]:
        if len(points) == 1:
            return points[0][1]
        span = points[1][0] - points[0][0]
        slope = (points[1][1] - points[0][1]) / span
        return points[0][1] + slope * (position - points[0][0])
    if position >= points[-1][0]:
        if len(points) == 1:
            return points[-1][1]
        span = points[-1][0] - points[-2][0]
        slope = (points[-1][1] - points[-2][1]) / span
        return points[-1][1] + slope * (position - points[-1][0])
    for index in range(len(points) - 1):
        left, right = points[index], points[index + 1]
        if left[0] <= position <= right[0]:
            fraction = (position - left[0]) / (right[0] - left[0])
            return left[1] + fraction * (right[1] - left[1])
    raise PrimariesError("tone curve interval was not found", code="CURVE")


def apply_tone_curve(rgb: Rgb, curve: Curve) -> Rgb:
    luma = linear_luma(rgb)
    delta = piecewise_linear(curve, luma) - luma
    return (rgb[0] + delta, rgb[1] + delta, rgb[2] + delta)


def primaries_saturation(rgb: Rgb, amount: float) -> Rgb:
    if not 0.0 <= amount <= 4.0:
        raise PrimariesError("saturation is outside 0 to 4", code="RANGE")
    luma = linear_luma(rgb)
    return (
        luma + amount * (rgb[0] - luma),
        luma + amount * (rgb[1] - luma),
        luma + amount * (rgb[2] - luma),
    )


def _finite_slider(value: float, minimum: float, maximum: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PrimariesError(f"{label} must be a finite number", code="RANGE")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise PrimariesError(
            f"{label} is outside {minimum:g} to {maximum:g}", code="RANGE"
        )
    return number


def kelvin_tint_to_gains(kelvin: float, tint: float = 0.0) -> Rgb:
    """Map Kelvin/tint UI values to luma-preserving RGB balance gains.

    Mapping id: ``kelvin-tint-v1``. Neutral is 6500 K / tint 0 → (1,1,1) after
    luma normalization. Positive tint adds green; negative adds magenta. The
    blackbody basis reuses the existing Tanner Helland / FFmpeg coefficients so
    legacy warmth research stays comparable, but this path is not the legacy
    warmth slider and does not write grades.
    """
    temperature = _finite_slider(kelvin, MIN_KELVIN, MAX_KELVIN, "kelvin")
    tint_value = _finite_slider(tint, MIN_TINT, MAX_TINT, "tint")
    reference = blackbody_channel_gains(NEUTRAL_KELVIN)
    sample = blackbody_channel_gains(temperature)
    gains = (
        sample[0] / reference[0],
        sample[1] / reference[1],
        sample[2] / reference[2],
    )
    amount = tint_value / 100.0
    tinted = (
        gains[0] * (1.0 - TINT_MAGENTA_WEIGHT * amount),
        gains[1] * (1.0 + TINT_GREEN_WEIGHT * amount),
        gains[2] * (1.0 - TINT_MAGENTA_WEIGHT * amount),
    )
    clamped = tuple(min(100.0, max(0.01, channel)) for channel in tinted)
    # Force identity at the published neutral so floating error cannot drift UI.
    if abs(temperature - NEUTRAL_KELVIN) <= 1e-9 and abs(tint_value) <= 1e-12:
        return (1.0, 1.0, 1.0)
    # Return pre-normalized gains; primaries_balance applies luma normalization.
    return (clamped[0], clamped[1], clamped[2])


def tone_controls_to_curve(
    *,
    blacks: float = 0.0,
    shadows: float = 0.0,
    highlights: float = 0.0,
    whites: float = 0.0,
) -> tuple[tuple[float, float], ...]:
    """Map blacks/shadows/highlights/whites sliders to one monotone tone curve.

    Mapping id: ``tone-controls-v1``. Sliders are -100..100. The curve has five
    knots at x = 0, 0.25, 0.5, 0.75, 1. Endpoint lifts come from blacks/whites;
    the quarter and three-quarter knots come from shadows/highlights. Neutral
    zeros yield the identity ``[(0,0),(1,1)]`` (collapsed to two knots).
    """
    black = _finite_slider(blacks, TONE_SLIDER_MIN, TONE_SLIDER_MAX, "blacks")
    shadow = _finite_slider(shadows, TONE_SLIDER_MIN, TONE_SLIDER_MAX, "shadows")
    highlight = _finite_slider(
        highlights, TONE_SLIDER_MIN, TONE_SLIDER_MAX, "highlights"
    )
    white = _finite_slider(whites, TONE_SLIDER_MIN, TONE_SLIDER_MAX, "whites")
    if black == shadow == highlight == white == 0.0:
        return ((0.0, 0.0), (1.0, 1.0))

    def lift(value: float, scale: float) -> float:
        return (value / 100.0) * scale

    y0 = min(0.35, max(-0.05, lift(black, 0.25)))
    y1 = 0.25 + lift(shadow, 0.20)
    y2 = 0.5 + 0.5 * lift(shadow, 0.10) + 0.5 * lift(highlight, 0.10)
    y3 = 0.75 + lift(highlight, 0.20)
    y4 = min(1.05, max(0.65, 1.0 + lift(white, 0.25)))
    # Enforce strict monotone x and non-decreasing y by clamping forward.
    points = [(0.0, y0), (0.25, y1), (0.5, y2), (0.75, y3), (1.0, y4)]
    for index in range(1, len(points)):
        x_prev, y_prev = points[index - 1]
        x_cur, y_cur = points[index]
        points[index] = (x_cur, max(y_prev, y_cur))
    return tuple((float(x), float(y)) for x, y in points)


def apply_primaries(
    rgb: Rgb,
    *,
    exposure: float = 0.0,
    gains: Rgb = (1.0, 1.0, 1.0),
    contrast: float = 1.0,
    pivot: float = 0.18,
    tone: Curve = ((0.0, 0.0), (1.0, 1.0)),
    saturation: float = 1.0,
    kelvin: float | None = None,
    tint: float = 0.0,
    blacks: float = 0.0,
    shadows: float = 0.0,
    highlights: float = 0.0,
    whites: float = 0.0,
) -> Rgb:
    """Exposure, balance, contrast, tone, then saturation. No second tone mapping.

    Optional Kelvin/tint replace ``gains``. Optional tonal sliders replace
    ``tone`` through the published mappings.
    """
    balance = kelvin_tint_to_gains(kelvin, tint) if kelvin is not None else gains
    if any(value != 0.0 for value in (blacks, shadows, highlights, whites)):
        curve: Curve = tone_controls_to_curve(
            blacks=blacks, shadows=shadows, highlights=highlights, whites=whites
        )
    else:
        curve = tone
    balanced = primaries_balance(primaries_exposure(rgb, exposure), balance)
    contrasted = primaries_contrast(balanced, contrast, pivot)
    toned = apply_tone_curve(contrasted, curve)
    return primaries_saturation(toned, saturation)
