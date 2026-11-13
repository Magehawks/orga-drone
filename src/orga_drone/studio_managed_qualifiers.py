"""Read-only RGB/HSL/luma qualifiers for issue #357.

Qualifiers sample the step input once. This module does not write grades or
identify sky, water, or objects.
"""

from __future__ import annotations

import math

Rgb = tuple[float, float, float]
LUMA_WEIGHTS = (0.2126, 0.7152, 0.0722)


class ManagedQualifierError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def smoothstep(edge0: float, edge1: float, value: float) -> float:
    if edge1 == edge0:
        raise ManagedQualifierError("smoothstep edges must differ", code="QUALIFIER")
    amount = min(1.0, max(0.0, (value - edge0) / (edge1 - edge0)))
    return amount * amount * (3.0 - 2.0 * amount)


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


def encoded_luma(rgb: Rgb) -> float:
    return LUMA_WEIGHTS[0] * rgb[0] + LUMA_WEIGHTS[1] * rgb[1] + LUMA_WEIGHTS[2] * rgb[2]


def interval_coverage(value: float, inner: float, outer: float) -> float:
    """Inner is fully selected, outer is zero. Joined by smoothstep either side."""
    if not all(math.isfinite(part) for part in (value, inner, outer)):
        raise ManagedQualifierError("interval values must be finite", code="QUALIFIER")
    if inner == outer:
        return 1.0 if value == inner else 0.0
    return smoothstep(outer, inner, value)


def hue_interval_coverage(hue: float, inner: float, outer: float) -> float:
    """Wrapped hue interval. Gray samples must be rejected by the caller."""
    if not all(math.isfinite(part) for part in (hue, inner, outer)):
        raise ManagedQualifierError("hue interval must be finite", code="QUALIFIER")
    span = (outer - inner) % 360.0
    if span == 0.0 and inner != outer:
        span = 360.0
    if span == 0.0:
        return 1.0 if (hue % 360.0) == (inner % 360.0) else 0.0
    # Distance from the centre of the selected arc, mapped to [0, span/2].
    center = (inner + span / 2.0) % 360.0
    delta = abs(((hue - center + 180.0) % 360.0) - 180.0)
    half = span / 2.0
    soft = max(0.0, half * 0.25)
    hard = half
    if delta <= hard - soft:
        return 1.0
    if delta >= hard:
        return 0.0
    return 1.0 - smoothstep(hard - soft, hard, delta)


def rgb_qualifier(rgb: Rgb, channels: tuple[tuple[float, float], ...]) -> float:
    if len(channels) != 3:
        raise ManagedQualifierError("RGB qualifier needs three intervals", code="QUALIFIER")
    coverage = 1.0
    for index, (inner, outer) in enumerate(channels):
        coverage *= interval_coverage(rgb[index], inner, outer)
    return min(1.0, max(0.0, coverage))


def hsl_qualifier(
    rgb: Rgb,
    *,
    hue: tuple[float, float] | None = None,
    saturation: tuple[float, float] | None = None,
    lightness: tuple[float, float] | None = None,
) -> float:
    sample_h, sample_s, sample_l = rgb_to_hsl(rgb)
    coverage = 1.0
    if hue is not None:
        if sample_s < 1e-6:
            return 0.0
        coverage *= hue_interval_coverage(sample_h, hue[0], hue[1])
    if saturation is not None:
        coverage *= interval_coverage(sample_s, saturation[0], saturation[1])
    if lightness is not None:
        coverage *= interval_coverage(sample_l, lightness[0], lightness[1])
    return min(1.0, max(0.0, coverage))


def luma_qualifier(rgb: Rgb, inner: float, outer: float) -> float:
    return interval_coverage(encoded_luma(rgb), inner, outer)


def selection_coverage(mask_coverage: float, qualifier_coverage: float, *, invert: bool = False) -> float:
    if not 0.0 <= mask_coverage <= 1.0 or not 0.0 <= qualifier_coverage <= 1.0:
        raise ManagedQualifierError("coverage must be from 0 to 1", code="QUALIFIER")
    coverage = mask_coverage * qualifier_coverage
    if invert:
        coverage = 1.0 - coverage
    return coverage


def step_blend(step_input: Rgb, processed: Rgb, mix: float, coverage: float) -> Rgb:
    if not 0.0 <= mix <= 1.0 or not 0.0 <= coverage <= 1.0:
        raise ManagedQualifierError("mix and coverage must be from 0 to 1", code="QUALIFIER")
    factor = mix * coverage
    return (
        step_input[0] + factor * (processed[0] - step_input[0]),
        step_input[1] + factor * (processed[1] - step_input[1]),
        step_input[2] + factor * (processed[2] - step_input[2]),
    )


def eyedropper_sample(
    rgb: Rgb,
    *,
    frame: int,
    revision: int,
    domain: str,
    neighborhood: tuple[float, float, float, float],
) -> dict[str, object]:
    """Return sample metadata. Never mutates a grade."""
    if domain not in {"bt709", "srgb", "legacy-native"}:
        raise ManagedQualifierError("unsupported sample domain", code="QUALIFIER")
    return {
        "rgb": rgb,
        "hsl": rgb_to_hsl(rgb),
        "luma": encoded_luma(rgb),
        "frame": int(frame),
        "revision": int(revision),
        "domain": domain,
        "neighborhood": neighborhood,
    }


# Re-export step blend so qualifier+mask fixtures stay in one import surface.
__all__ = [
    "ManagedQualifierError",
    "eyedropper_sample",
    "hsl_qualifier",
    "luma_qualifier",
    "rgb_qualifier",
    "selection_coverage",
    "step_blend",
]
