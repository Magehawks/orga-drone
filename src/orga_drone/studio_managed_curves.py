"""Read-only managed curve operators for issue #354.

Seven curve families from ADR 0035. No UI, no database write, and no change to
the legacy HSL or image grade path.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

LUMA_WEIGHTS = (0.2126, 0.7152, 0.0722)
IDENTITY_CURVE: tuple[tuple[float, float], ...] = ((0.0, 0.0), (1.0, 1.0))
MAX_CURVE_POINTS = 64
Rgb = tuple[float, float, float]
Curve = Sequence[tuple[float, float]]


class ManagedCurveError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _require_curve(points: Curve, *, periodic_hue: bool = False) -> tuple[tuple[float, float], ...]:
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
        raise ManagedCurveError("curve must be a sequence of points", code="CURVE")
    if len(points) < 1:
        raise ManagedCurveError("a curve needs at least one point", code="CURVE")
    if len(points) > MAX_CURVE_POINTS:
        raise ManagedCurveError(
            f"a curve may have at most {MAX_CURVE_POINTS} points",
            code="CURVE",
        )
    cleaned: list[tuple[float, float]] = []
    for point in points:
        if not isinstance(point, Sequence) or len(point) != 2:
            raise ManagedCurveError("each curve point needs x and y", code="CURVE")
        x_value, y_value = float(point[0]), float(point[1])
        if not math.isfinite(x_value) or not math.isfinite(y_value):
            raise ManagedCurveError("curve points must be finite", code="CURVE")
        cleaned.append((x_value, y_value))
    for index in range(len(cleaned) - 1):
        if cleaned[index][0] >= cleaned[index + 1][0]:
            raise ManagedCurveError("curve x values must increase", code="CURVE")
    if periodic_hue:
        if cleaned[0][0] != 0.0 or cleaned[-1][0] != 360.0:
            raise ManagedCurveError(
                "hue curves must start at 0 and end at 360",
                code="CURVE",
            )
        if cleaned[0][1] != cleaned[-1][1]:
            raise ManagedCurveError(
                "hue curve endpoints must match",
                code="CURVE",
            )
    return tuple(cleaned)


def piecewise_linear(points: Curve, position: float) -> float:
    curve = _require_curve(points)
    if not math.isfinite(position):
        raise ManagedCurveError("sample position must be finite", code="CURVE")
    if position <= curve[0][0]:
        if len(curve) == 1:
            return curve[0][1]
        span = curve[1][0] - curve[0][0]
        slope = (curve[1][1] - curve[0][1]) / span
        return curve[0][1] + slope * (position - curve[0][0])
    if position >= curve[-1][0]:
        if len(curve) == 1:
            return curve[-1][1]
        span = curve[-1][0] - curve[-2][0]
        slope = (curve[-1][1] - curve[-2][1]) / span
        return curve[-1][1] + slope * (position - curve[-1][0])
    for index in range(len(curve) - 1):
        left, right = curve[index], curve[index + 1]
        if left[0] <= position <= right[0]:
            fraction = (position - left[0]) / (right[0] - left[0])
            return left[1] + fraction * (right[1] - left[1])
    raise ManagedCurveError("curve interval was not found", code="CURVE")


def linear_luma(rgb: Rgb) -> float:
    return LUMA_WEIGHTS[0] * rgb[0] + LUMA_WEIGHTS[1] * rgb[1] + LUMA_WEIGHTS[2] * rgb[2]


def rgb_to_hsl(rgb: Rgb) -> tuple[float, float, float]:
    red, green, blue = rgb
    maximum, minimum = max(rgb), min(rgb)
    lightness = (maximum + minimum) / 2.0
    delta = maximum - minimum
    if delta <= 1e-12:
        return (0.0, 0.0, lightness)
    denominator = 1.0 - abs(2.0 * lightness - 1.0)
    saturation = 0.0 if denominator <= 1e-12 else delta / denominator
    if maximum == red:
        hue = ((green - blue) / delta) % 6.0
    elif maximum == green:
        hue = (blue - red) / delta + 2.0
    else:
        hue = (red - green) / delta + 4.0
    return (hue * 60.0, saturation, lightness)


def hsl_to_rgb(hue: float, saturation: float, lightness: float) -> Rgb:
    if saturation <= 1e-12:
        value = min(1.0, max(0.0, lightness))
        return (value, value, value)
    channel2 = (
        lightness * (1.0 + saturation)
        if lightness < 0.5
        else lightness + saturation - lightness * saturation
    )
    channel1 = 2.0 * lightness - channel2
    hue_norm = (hue % 360.0) / 360.0

    def channel(offset: float) -> float:
        value = (hue_norm + offset) % 1.0
        if value < 1.0 / 6.0:
            return channel1 + (channel2 - channel1) * 6.0 * value
        if value < 0.5:
            return channel2
        if value < 2.0 / 3.0:
            return channel1 + (channel2 - channel1) * 6.0 * (2.0 / 3.0 - value)
        return channel1

    return (channel(1.0 / 3.0), channel(0.0), channel(-1.0 / 3.0))


def shortest_hue_offset(delta_deg: float) -> float:
    return (delta_deg + 180.0) % 360.0 - 180.0


def is_gray(rgb: Rgb) -> bool:
    return rgb_to_hsl(rgb)[1] < 1e-6 or (max(rgb) - min(rgb)) < 1e-6


def rgb_curves_v1(
    rgb: Rgb,
    master: Curve = IDENTITY_CURVE,
    channels: tuple[Curve, Curve, Curve] = (
        IDENTITY_CURVE,
        IDENTITY_CURVE,
        IDENTITY_CURVE,
    ),
) -> Rgb:
    """Master curve first, then each channel curve. Identity is [(0,0),(1,1)]."""
    after_master = (
        piecewise_linear(master, rgb[0]),
        piecewise_linear(master, rgb[1]),
        piecewise_linear(master, rgb[2]),
    )
    return (
        piecewise_linear(channels[0], after_master[0]),
        piecewise_linear(channels[1], after_master[1]),
        piecewise_linear(channels[2], after_master[2]),
    )


def luma_curve_v1(rgb: Rgb, curve: Curve = IDENTITY_CURVE) -> Rgb:
    luma = linear_luma(rgb)
    delta = piecewise_linear(curve, luma) - luma
    return (rgb[0] + delta, rgb[1] + delta, rgb[2] + delta)


def hue_vs_hue(rgb: Rgb, curve: Curve) -> Rgb:
    _require_curve(curve, periodic_hue=True)
    if is_gray(rgb):
        return rgb
    hue, saturation, lightness = rgb_to_hsl(rgb)
    shifted = (hue + shortest_hue_offset(piecewise_linear(curve, hue))) % 360.0
    return hsl_to_rgb(
        shifted,
        min(1.0, max(0.0, saturation)),
        min(1.0, max(0.0, lightness)),
    )


def hue_vs_saturation(rgb: Rgb, curve: Curve) -> Rgb:
    _require_curve(curve, periodic_hue=True)
    if is_gray(rgb):
        return rgb
    hue, saturation, lightness = rgb_to_hsl(rgb)
    new_s = min(1.0, max(0.0, saturation * piecewise_linear(curve, hue)))
    return hsl_to_rgb(hue, new_s, min(1.0, max(0.0, lightness)))


def hue_vs_luma(rgb: Rgb, curve: Curve) -> Rgb:
    _require_curve(curve, periodic_hue=True)
    if is_gray(rgb):
        return rgb
    hue, saturation, lightness = rgb_to_hsl(rgb)
    new_l = min(1.0, max(0.0, lightness + piecewise_linear(curve, hue)))
    return hsl_to_rgb(hue, min(1.0, max(0.0, saturation)), new_l)


def luma_vs_saturation(rgb: Rgb, curve: Curve) -> Rgb:
    hue, saturation, lightness = rgb_to_hsl(rgb)
    encoded = LUMA_WEIGHTS[0] * rgb[0] + LUMA_WEIGHTS[1] * rgb[1] + LUMA_WEIGHTS[2] * rgb[2]
    new_s = min(1.0, max(0.0, saturation * piecewise_linear(curve, encoded)))
    return hsl_to_rgb(hue, new_s, min(1.0, max(0.0, lightness)))


def saturation_vs_saturation(rgb: Rgb, curve: Curve) -> Rgb:
    hue, saturation, lightness = rgb_to_hsl(rgb)
    new_s = min(1.0, max(0.0, piecewise_linear(curve, saturation)))
    return hsl_to_rgb(hue, new_s, min(1.0, max(0.0, lightness)))
