"""Independent reference math for the Color Workspace contract (ADR 0035).

OpenCode evidence lane: this module re-implements the pure arithmetic that
``docs/architecture/COLOR_WORKSPACE_CONTRACT.md`` specifies, from the contract
text alone. It is the oracle the engine implementation (#350+) must agree
with; it is never imported by production code and never monkeypatches it.

Published vectors that pin this math live in
``docs/architecture/COLOR_WORKSPACE_REVIEW_EVIDENCE.md`` and are asserted in
``tests/test_color_workspace_reference_vectors.py``.

Contract revision: ADR 0035 / contract as merged with PR #367 (baseline
develop 8ff2545).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Sequence

LUMA_WEIGHTS = (0.2126, 0.7152, 0.0722)


# ---------------------------------------------------------------------------
# Transfers (contract: "Managed SDR numerical contract")
# ---------------------------------------------------------------------------


def encode_srgb(linear: float) -> float:
    """S(L): sRGB OETF. 12.92*L when L<=.0031308, else 1.055*L**(1/2.4)-.055."""
    return 12.92 * linear if linear <= 0.0031308 else 1.055 * linear ** (1 / 2.4) - 0.055


def encode_bt709(linear: float) -> float:
    """B(L): BT.709 OETF. 4.5*L when L<.018, else 1.099*L**.45-.099."""
    return 4.5 * linear if linear < 0.018 else 1.099 * linear ** 0.45 - 0.099


def decode_srgb(c: float) -> float:
    """D_s(c) = c/12.92 when c<=.04045 else ((c+.055)/1.055)**2.4."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def decode_bt709(c: float) -> float:
    """D_b(c) = c/4.5 when c<.081 else ((c+.099)/1.099)**(1/.45)."""
    return c / 4.5 if c < 0.081 else ((c + 0.099) / 1.099) ** (1 / 0.45)


def q8(x: float) -> int:
    """Q8(x)=floor(255*clamp(x,0,1)+.5), ties upward, no dither."""
    return math.floor(255 * min(1.0, max(0.0, x)) + 0.5)


def luma(rgb: tuple[float, float, float]) -> float:
    """Linear BT.709 luma Y = .2126 R + .7152 G + .0722 B."""
    return LUMA_WEIGHTS[0] * rgb[0] + LUMA_WEIGHTS[1] * rgb[1] + LUMA_WEIGHTS[2] * rgb[2]


# ---------------------------------------------------------------------------
# primaries-v1 (contract: exposure -> balance -> contrast -> tone -> saturation)
# ---------------------------------------------------------------------------


def primaries_exposure(rgb: tuple[float, float, float], stops: float) -> tuple[float, float, float]:
    """Exposure E in stops [-10,10]: RGB *= 2^E."""
    if not -10.0 <= stops <= 10.0:
        raise ValueError("exposure out of contract range")
    factor = 2.0 ** stops
    return (rgb[0] * factor, rgb[1] * factor, rgb[2] * factor)


def primaries_balance(
    rgb: tuple[float, float, float], gains: tuple[float, float, float]
) -> tuple[float, float, float]:
    """Positive RGB gains [.01,100] normalized so the luma-weighted sum is 1,
    applied diagonally in linear RGB. Identity is [1,1,1]."""
    if not all(0.01 <= gain <= 100.0 for gain in gains):
        raise ValueError("balance gains out of contract range")
    weighted = sum(LUMA_WEIGHTS[i] * gains[i] for i in range(3))
    scale = 1.0 / weighted
    return tuple(gains[i] * scale * rgb[i] for i in range(3))  # type: ignore[return-value]


def primaries_contrast(rgb: tuple[float, float, float], k: float, pivot: float) -> tuple[float, float, float]:
    """Contrast k in [0,4], pivot p in [.001,1]:
    p * sign(RGB/p) * abs(RGB/p)^k. k=1 identity; k=0 -> p/-p/0."""
    if not 0.0 <= k <= 4.0:
        raise ValueError("contrast out of contract range")
    if not 0.001 <= pivot <= 1.0:
        raise ValueError("pivot out of contract range")
    result = []
    for channel in rgb:
        ratio = channel / pivot
        if k == 0.0:
            result.append(math.copysign(pivot, ratio) if channel != 0.0 else 0.0)
        else:
            result.append(pivot * math.copysign(abs(ratio) ** k, ratio))
    return (result[0], result[1], result[2])


def apply_tone_curve(
    rgb: tuple[float, float, float], curve: Sequence[tuple[float, float]]
) -> tuple[float, float, float]:
    """Tone: monotone piecewise-linear scalar Y map with endpoint extension;
    RGB += f(Y) - Y. Defaults [(0,0),(1,1)] (identity)."""
    y = luma(rgb)
    f_y = piecewise_linear(curve, y)
    delta = f_y - y
    return (rgb[0] + delta, rgb[1] + delta, rgb[2] + delta)


def primaries_saturation(
    rgb: tuple[float, float, float], saturation: float
) -> tuple[float, float, float]:
    """Saturation s in [0,4]: Y + s*(RGB-Y). s=1 identity."""
    if not 0.0 <= saturation <= 4.0:
        raise ValueError("saturation out of contract range")
    y = luma(rgb)
    return tuple(y + saturation * (channel - y) for channel in rgb)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Curves (contract: "Curves, HSL and serial operations")
# ---------------------------------------------------------------------------


def piecewise_linear(points: Sequence[tuple[float, float]], x: float) -> float:
    """Piecewise-linear interpolation with strictly increasing x and
    endpoint-segment extrapolation."""
    if len(points) < 1:
        raise ValueError("curve needs at least one point")
    ordered = sorted(points, key=lambda point: point[0])
    if any(
        ordered[i][0] >= ordered[i + 1][0] for i in range(len(ordered) - 1)
    ):
        raise ValueError("curve x values must be strictly increasing")
    if x <= ordered[0][0]:
        first, second = ordered[0], ordered[1] if len(ordered) > 1 else ordered[0]
        if second == first:
            return first[1]
        slope = (second[1] - first[1]) / (second[0] - first[0])
        return first[1] + slope * (x - first[0])
    if x >= ordered[-1][0]:
        last, previous = ordered[-1], ordered[-2] if len(ordered) > 1 else ordered[-1]
        if previous == last:
            return last[1]
        slope = (last[1] - previous[1]) / (last[0] - previous[0])
        return last[1] + slope * (x - last[0])
    for index in range(len(ordered) - 1):
        left, right = ordered[index], ordered[index + 1]
        if left[0] <= x <= right[0]:
            fraction = (x - left[0]) / (right[0] - left[0])
            return left[1] + fraction * (right[1] - left[1])
    raise AssertionError("unreachable: interval search failed")


def rgb_curves_v1(
    rgb: tuple[float, float, float],
    master: Sequence[tuple[float, float]],
    channels: tuple[
        Sequence[tuple[float, float]],
        Sequence[tuple[float, float]],
        Sequence[tuple[float, float]],
    ],
) -> tuple[float, float, float]:
    """rgb-curves-v1: evaluate the master curve on each channel first, then
    each channel's own curve. Identity is [(0,0),(1,1)]."""
    identity = ((0.0, 0.0), (1.0, 1.0))
    master_curve = master if master else identity
    after_master = tuple(piecewise_linear(master_curve, channel) for channel in rgb)  # type: ignore[var-annotated]
    return tuple(
        piecewise_linear(channels[i] if channels[i] else identity, after_master[i])  # type: ignore[arg-type]
        for i in range(3)
    )  # type: ignore[return-value]


def luma_curve_v1(
    rgb: tuple[float, float, float], curve: Sequence[tuple[float, float]]
) -> tuple[float, float, float]:
    """luma-curve-v1: map Y and add f(Y)-Y to RGB (behavior at black without
    division)."""
    return apply_tone_curve(rgb, curve)


# ---------------------------------------------------------------------------
# wheels-v1 (contract: lift/gamma/gain/offset)
# ---------------------------------------------------------------------------


def wheels_v1_channel(
    x: float, *, lift: float, gamma: float, gain: float, offset: float
) -> float:
    """Per channel: sign(z)*abs(z)^(1/gamma)+offset with z=(x+lift)*gain.
    gain>=0, gamma>0, lift/offset finite. Neutral: lift/offset=0, gamma=gain=1."""
    if gamma <= 0.0:
        raise ValueError("gamma must be > 0")
    if gain < 0.0:
        raise ValueError("gain must be >= 0")
    z = (x + lift) * gain
    return math.copysign(abs(z) ** (1.0 / gamma), z) + offset


def wheels_v1(
    rgb: tuple[float, float, float],
    *,
    lift: float = 0.0,
    gamma: float = 1.0,
    gain: float = 1.0,
    offset: float = 0.0,
) -> tuple[float, float, float]:
    return tuple(  # type: ignore[return-value]
        wheels_v1_channel(channel, lift=lift, gamma=gamma, gain=gain, offset=offset)
        for channel in rgb
    )


# ---------------------------------------------------------------------------
# Encoded-domain HSL operations (contract: "Curves, HSL and serial operations")
# ---------------------------------------------------------------------------


def rgb_to_hsl(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    """RGB/HSL definitions per the existing studio_hsl.py semantics
    (hue in degrees, saturation/lightness in [0,1])."""
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


def hsl_to_rgb(hue: float, saturation: float, lightness: float) -> tuple[float, float, float]:
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

    def hue_channel(offset: float) -> float:
        value = (hue_norm + offset) % 1.0
        if value < 1.0 / 6.0:
            return channel1 + (channel2 - channel1) * 6.0 * value
        if value < 0.5:
            return channel2
        if value < 2.0 / 3.0:
            return channel1 + (channel2 - channel1) * 6.0 * (2.0 / 3.0 - value)
        return channel1

    return (hue_channel(1.0 / 3.0), hue_channel(0.0), hue_channel(-1.0 / 3.0))


def shortest_hue_offset(delta_deg: float) -> float:
    """Shortest signed hue offset; hue is periodic at 360 degrees."""
    return (delta_deg + 180.0) % 360.0 - 180.0


def hue_vs_hue(rgb: tuple[float, float, float], curve: Sequence[tuple[float, float]]) -> tuple[float, float, float]:
    """Hue-vs-Hue: add curve(hue) degrees via the shortest signed offset."""
    if rgb_to_hsl(rgb)[1] < 1e-6 or (max(rgb) - min(rgb)) < 1e-6:
        return rgb
    hue, saturation, lightness = rgb_to_hsl(rgb)
    shifted = (hue + shortest_hue_offset(piecewise_linear(curve, hue))) % 360.0
    return hsl_to_rgb(shifted, min(1.0, max(0.0, saturation)), min(1.0, max(0.0, lightness)))


def hue_vs_saturation(rgb: tuple[float, float, float], curve: Sequence[tuple[float, float]]) -> tuple[float, float, float]:
    """Hue-vs-Saturation: multiply S by curve(hue); clamp S after."""
    if rgb_to_hsl(rgb)[1] < 1e-6 or (max(rgb) - min(rgb)) < 1e-6:
        return rgb
    hue, saturation, lightness = rgb_to_hsl(rgb)
    new_s = min(1.0, max(0.0, saturation * piecewise_linear(curve, hue)))
    return hsl_to_rgb(hue, new_s, min(1.0, max(0.0, lightness)))


def hue_vs_luma(rgb: tuple[float, float, float], curve: Sequence[tuple[float, float]]) -> tuple[float, float, float]:
    """Hue-vs-Luma: add L = curve(hue); clamp L after."""
    if rgb_to_hsl(rgb)[1] < 1e-6 or (max(rgb) - min(rgb)) < 1e-6:
        return rgb
    hue, saturation, lightness = rgb_to_hsl(rgb)
    new_l = min(1.0, max(0.0, lightness + piecewise_linear(curve, hue)))
    return hsl_to_rgb(hue, min(1.0, max(0.0, saturation)), new_l)


def luma_vs_saturation(rgb: tuple[float, float, float], curve: Sequence[tuple[float, float]]) -> tuple[float, float, float]:
    """Luma-vs-Saturation: multiply S by curve(encoded BT.709 luma); clamp."""
    encoded_luma = (
        LUMA_WEIGHTS[0] * rgb[0] + LUMA_WEIGHTS[1] * rgb[1] + LUMA_WEIGHTS[2] * rgb[2]
    )
    _, saturation, lightness = rgb_to_hsl(rgb)
    new_s = min(1.0, max(0.0, saturation * piecewise_linear(curve, encoded_luma)))
    hue, _, _ = rgb_to_hsl(rgb)
    return hsl_to_rgb(hue, new_s, min(1.0, max(0.0, lightness)))


def saturation_vs_saturation(rgb: tuple[float, float, float], curve: Sequence[tuple[float, float]]) -> tuple[float, float, float]:
    """Saturation-vs-Saturation: map S directly; clamp after."""
    hue, saturation, lightness = rgb_to_hsl(rgb)
    new_s = min(1.0, max(0.0, piecewise_linear(curve, saturation)))
    return hsl_to_rgb(hue, new_s, min(1.0, max(0.0, lightness)))


# ---------------------------------------------------------------------------
# 3D LUT sampling (contract: "LUT assets and sampling")
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CubeLut:
    """Parsed 3D cube: red-fastest data, size N (2..65), declared domain."""

    size: int
    data: tuple[tuple[float, float, float], ...]
    domain_min: tuple[float, float, float] = (0.0, 0.0, 0.0)
    domain_max: tuple[float, float, float] = (1.0, 1.0, 1.0)


def parse_cube_text(text: str) -> CubeLut:
    """Contract parser: red-fastest, exactly N^3 finite triples,
    2<=N<=65, reject duplicate headers / malformed domains."""
    size: int | None = None
    domain_min = [0.0, 0.0, 0.0]
    domain_max = [1.0, 1.0, 1.0]
    triples: list[tuple[float, float, float]] = []
    seen_headers = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        upper = line.upper()
        if upper.startswith("TITLE"):
            continue
        if upper.startswith("LUT_3D_SIZE"):
            if seen_headers:
                raise ValueError("duplicate LUT_3D_SIZE header")
            seen_headers += 1
            size = int(upper.split()[1])
            if not 2 <= size <= 65:
                raise ValueError("LUT_3D_SIZE out of contract range 2..65")
            continue
        if upper.startswith(("DOMAIN_MIN", "DOMAIN_MAX")):
            parts = line.split()
            values = [float(part) for part in parts[1:4]]
            target = domain_min if upper.startswith("DOMAIN_MIN") else domain_max
            for i, value in enumerate(values):
                target[i] = value
            if not all(
                math.isfinite(domain_min[i]) and math.isfinite(domain_max[i])
                for i in range(3)
            ):
                raise ValueError("nonfinite LUT domain")
            if any(domain_min[i] >= domain_max[i] for i in range(3)):
                raise ValueError("non-increasing LUT domain bounds")
            continue
        if upper.startswith(("LUT_1D_SIZE", "LUT_1D_INPUT_RANGE", "SHAPER_SIZE")):
            raise ValueError("1D/shaper LUT variants are not part of this contract")
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"malformed cube line: {line!r}")
        triple = tuple(float(part) for part in parts)
        if not all(math.isfinite(value) for value in triple):
            raise ValueError("nonfinite cube value")
        triples.append(triple)  # type: ignore[arg-type]
    if size is None:
        raise ValueError("missing LUT_3D_SIZE header")
    if len(triples) != size ** 3:
        raise ValueError(f"expected {size ** 3} triples, got {len(triples)}")
    return CubeLut(size=size, data=tuple(triples),  # type: ignore[arg-type]
                   domain_min=tuple(domain_min),  # type: ignore[arg-type]
                   domain_max=tuple(domain_max))  # type: ignore[arg-type]


def sample_lut(lut: CubeLut, rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    """u = clamp((c-domain_min)/(domain_max-domain_min),0,1)*(N-1); tetrahedral
    interpolation with descending fractional coordinates; ties resolve R
    before G before B. Indexing is red-fastest (r fastest, then g, then b)."""
    size = lut.size
    coords = []
    for i in range(3):
        span = lut.domain_max[i] - lut.domain_min[i]
        u = (rgb[i] - lut.domain_min[i]) / span
        u = min(1.0, max(0.0, u)) * (size - 1)
        coords.append(u)

    def vertex(red: int, green: int, blue: int) -> tuple[float, float, float]:
        index = red + green * size + blue * size * size
        return lut.data[index]

    # Sort axes by descending fractional part; ties resolve R before G
    # before B (ascending axis index as the secondary key).
    fractions = [coord % 1.0 for coord in coords]
    base = [int(coord) for coord in coords]
    a, b, c = sorted(range(3), key=lambda axis: (-fractions[axis], axis))
    fa, fb, fc = fractions[a], fractions[b], fractions[c]

    def vertex_at(offsets: tuple[int, int, int]) -> tuple[float, float, float]:
        scaled = [
            min(base[axis] + offsets[axis], size - 1) for axis in range(3)
        ]
        return vertex(scaled[0], scaled[1], scaled[2])

    def axis_unit(axis: int) -> tuple[int, int, int]:
        return (1 if axis == 0 else 0, 1 if axis == 1 else 0, 1 if axis == 2 else 0)

    def axes_union(first: int, second: int) -> tuple[int, int, int]:
        return (
            1 if first == 0 or second == 0 else 0,
            1 if first == 1 or second == 1 else 0,
            1 if first == 2 or second == 2 else 0,
        )

    v000 = vertex_at((0, 0, 0))
    va = vertex_at(axis_unit(a))
    vab = vertex_at(axes_union(a, b))
    v111 = vertex_at((1, 1, 1))
    return (
        v000[0] + fa * (va[0] - v000[0]) + fb * (vab[0] - va[0]) + fc * (v111[0] - vab[0]),
        v000[1] + fa * (va[1] - v000[1]) + fb * (vab[1] - va[1]) + fc * (v111[1] - vab[1]),
        v000[2] + fa * (va[2] - v000[2]) + fb * (vab[2] - va[2]) + fc * (v111[2] - vab[2]),
    )


def sample_creative_lut(
    lut: CubeLut, rgb: tuple[float, float, float], strength: float
) -> tuple[float, float, float]:
    """Creative strength m in [0,1]: (1-m)*input + m*sample.
    Zero strength bypasses both sample and its domain clamp."""
    if strength <= 0.0:
        return rgb
    if strength > 1.0:
        raise ValueError("creative strength above 1")
    sampled = sample_lut(lut, rgb)
    return tuple(  # type: ignore[return-value]
        (1.0 - strength) * rgb[i] + strength * sampled[i] for i in range(3)
    )


# ---------------------------------------------------------------------------
# Selections (contract: "Spatial selections and time")
# ---------------------------------------------------------------------------


def smoothstep(edge0: float, edge1: float, x: float) -> float:
    """t=clamp((x-edge0)/(edge1-edge0),0,1); t*t*(3-2t)."""
    if edge1 == edge0:
        raise ValueError("degenerate smoothstep interval")
    t = min(1.0, max(0.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def signed_distance_to_line(
    point: tuple[float, float], line_a: tuple[float, float], line_b: tuple[float, float]
) -> float:
    """Signed distance to the (infinite) normalized line through a/b."""
    ax, ay = line_a
    bx, by = line_b
    length = math.hypot(bx - ax, by - ay)
    if length <= 0.0:
        raise ValueError("degenerate line")
    # Cross product gives signed area; divide by length for distance.
    return ((bx - ax) * (point[1] - ay) - (by - ay) * (point[0] - ax)) / length


def linear_mask_coverage(
    point: tuple[float, float],
    line_a: tuple[float, float],
    line_b: tuple[float, float],
    feather: float,
) -> float:
    """Linear coverage: smoothstep(-f/2, f/2, d) on signed distance; at f=0 a
    hard threshold."""
    distance = signed_distance_to_line(point, line_a, line_b)
    if feather == 0.0:
        return 1.0 if distance <= 0.0 else 0.0
    return smoothstep(-feather / 2.0, feather / 2.0, distance)


def elliptical_radius(
    point: tuple[float, float], center: tuple[float, float], axes: tuple[float, float]
) -> float:
    """Normalized elliptical radius of a point around a center."""
    dx = (point[0] - center[0]) / axes[0]
    dy = (point[1] - center[1]) / axes[1]
    return math.hypot(dx, dy)


def radial_mask_coverage(
    point: tuple[float, float],
    center: tuple[float, float],
    axes: tuple[float, float],
    feather: float,
) -> float:
    """Radial coverage: 1 - smoothstep(1-f, 1+f, r) on elliptical radius; at
    f=0 a hard threshold."""
    radius = elliptical_radius(point, center, axes)
    if feather == 0.0:
        return 1.0 if radius <= 1.0 else 0.0
    return 1.0 - smoothstep(1.0 - feather, 1.0 + feather, radius)


def combine_mask_leaves(
    coverages: Sequence[float], combine: Callable[[float, float], float]
) -> float:
    """Union=max, intersection=min, subtraction=max(0, a-b) fold left."""
    if not coverages:
        return 0.0
    result = coverages[0]
    for value in coverages[1:]:
        result = combine(result, value)
    return min(1.0, max(0.0, result))


def union(a: float, b: float) -> float:
    return max(a, b)


def intersection(a: float, b: float) -> float:
    return min(a, b)


def subtraction(a: float, b: float) -> float:
    return max(0.0, a - b)


def qualifier_interval_coverage(x: float, inner: float, outer: float) -> float:
    """Interval selector: inner fully-selected, outer zero-selected bounds
    joined by smoothstep."""
    if inner > outer:
        raise ValueError("inner bound exceeds outer bound")
    if inner == outer:
        return 1.0 if inner <= x <= outer else 0.0
    return smoothstep(outer, inner, x)


def step_blend(
    step_input: tuple[float, float, float],
    processed: tuple[float, float, float],
    mix: float,
    coverage: float,
) -> tuple[float, float, float]:
    """For step input C, processed P, mix m and coverage q:
    output C + m*q*(P-C). Alpha is unchanged (not carried here)."""
    if not 0.0 <= mix <= 1.0:
        raise ValueError("mix out of [0,1]")
    if not 0.0 <= coverage <= 1.0:
        raise ValueError("coverage out of [0,1]")
    factor = mix * coverage
    return tuple(  # type: ignore[return-value]
        step_input[i] + factor * (processed[i] - step_input[i]) for i in range(3)
    )
