"""Read-only wheels-v1 and managed HSL adapters for issue #355.

Legacy HSL and tonal wheels stay on their existing modules. This file does not
write grades or change the encoder.
"""

from __future__ import annotations

import math

Rgb = tuple[float, float, float]


class ManagedWheelsError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def wheels_channel(
    value: float,
    *,
    lift: float = 0.0,
    gamma: float = 1.0,
    gain: float = 1.0,
    offset: float = 0.0,
) -> float:
    """sign(z)*abs(z)^(1/gamma)+offset with z=(x+lift)*gain."""
    if not math.isfinite(value) or not all(
        math.isfinite(part) for part in (lift, gamma, gain, offset)
    ):
        raise ManagedWheelsError("wheel parameters must be finite", code="RANGE")
    if gamma <= 0.0:
        raise ManagedWheelsError("gamma must be greater than zero", code="RANGE")
    if gain < 0.0:
        raise ManagedWheelsError("gain must be at least zero", code="RANGE")
    scaled = (value + lift) * gain
    return math.copysign(abs(scaled) ** (1.0 / gamma), scaled) + offset


def wheels_v1(
    rgb: Rgb,
    *,
    lift: float = 0.0,
    gamma: float = 1.0,
    gain: float = 1.0,
    offset: float = 0.0,
) -> Rgb:
    return (
        wheels_channel(rgb[0], lift=lift, gamma=gamma, gain=gain, offset=offset),
        wheels_channel(rgb[1], lift=lift, gamma=gamma, gain=gain, offset=offset),
        wheels_channel(rgb[2], lift=lift, gamma=gamma, gain=gain, offset=offset),
    )


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


def managed_hsl(
    rgb: Rgb,
    *,
    hue_offset_deg: float = 0.0,
    saturation_mult: float = 1.0,
    lightness_offset: float = 0.0,
) -> Rgb:
    """Encoded-domain HSL step. Neutral: hue 0, saturation 1, lightness 0."""
    if not all(
        math.isfinite(part)
        for part in (hue_offset_deg, saturation_mult, lightness_offset)
    ):
        raise ManagedWheelsError("HSL parameters must be finite", code="RANGE")
    hue, saturation, lightness = rgb_to_hsl(rgb)
    return hsl_to_rgb(
        (hue + hue_offset_deg) % 360.0,
        min(1.0, max(0.0, saturation * saturation_mult)),
        min(1.0, max(0.0, lightness + lightness_offset)),
    )


def compose_serial(rgb: Rgb, steps: tuple[tuple[str, dict[str, float]], ...]) -> Rgb:
    """Apply named managed steps in order. Unknown names fail atomically."""
    current = rgb
    for name, params in steps:
        if name == "wheels-v1":
            current = wheels_v1(current, **params)
        elif name == "managed-hsl-v1":
            current = managed_hsl(current, **params)
        else:
            raise ManagedWheelsError(f"unsupported step: {name}", code="UNSUPPORTED")
    return current
