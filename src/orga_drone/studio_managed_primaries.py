"""Read-only primaries-v1 arithmetic for issue #353.

Kelvin/tint and blacks/shadows/highlights/whites stay unpublished. This module
does not write grades and does not change the legacy exposure or warmth path.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

LUMA_WEIGHTS = (0.2126, 0.7152, 0.0722)
Rgb = tuple[float, float, float]
Curve = Sequence[tuple[float, float]]


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


def apply_primaries(
    rgb: Rgb,
    *,
    exposure: float = 0.0,
    gains: Rgb = (1.0, 1.0, 1.0),
    contrast: float = 1.0,
    pivot: float = 0.18,
    tone: Curve = ((0.0, 0.0), (1.0, 1.0)),
    saturation: float = 1.0,
) -> Rgb:
    """Exposure, balance, contrast, tone, then saturation. No second tone mapping."""
    balanced = primaries_balance(primaries_exposure(rgb, exposure), gains)
    contrasted = primaries_contrast(balanced, contrast, pivot)
    toned = apply_tone_curve(contrasted, tone)
    return primaries_saturation(toned, saturation)
