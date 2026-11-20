"""Read-only linear, radial and brush matte math for issue #356.

Selections are source-oriented. This module does not write grades, replace the
privacy mask, or add tracking.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Point = tuple[float, float]
Rgb = tuple[float, float, float]


class ManagedMaskError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def smoothstep(edge0: float, edge1: float, value: float) -> float:
    if edge1 == edge0:
        raise ManagedMaskError("smoothstep edges must differ", code="MASK")
    amount = min(1.0, max(0.0, (value - edge0) / (edge1 - edge0)))
    return amount * amount * (3.0 - 2.0 * amount)


def signed_distance_to_line(point: Point, start: Point, end: Point) -> float:
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    if length <= 0.0:
        raise ManagedMaskError("mask line is degenerate", code="MASK")
    return (
        (end[0] - start[0]) * (point[1] - start[1])
        - (end[1] - start[1]) * (point[0] - start[0])
    ) / length


def linear_coverage(
    point: Point,
    start: Point,
    end: Point,
    feather: float,
) -> float:
    """smoothstep(-f/2, f/2, d). Feather 0 is a hard threshold."""
    if feather < 0.0:
        raise ManagedMaskError("feather must be at least zero", code="MASK")
    distance = signed_distance_to_line(point, start, end)
    if feather == 0.0:
        return 1.0 if distance <= 0.0 else 0.0
    return smoothstep(-feather / 2.0, feather / 2.0, distance)


def radial_coverage(
    point: Point,
    center: Point,
    axes: Point,
    feather: float,
) -> float:
    """1 - smoothstep(1-f, 1+f, r) on elliptical radius."""
    if axes[0] <= 0.0 or axes[1] <= 0.0:
        raise ManagedMaskError("radial axes must be positive", code="MASK")
    if feather < 0.0:
        raise ManagedMaskError("feather must be at least zero", code="MASK")
    radius = math.hypot(
        (point[0] - center[0]) / axes[0],
        (point[1] - center[1]) / axes[1],
    )
    if feather == 0.0:
        return 1.0 if radius <= 1.0 else 0.0
    return 1.0 - smoothstep(1.0 - feather, 1.0 + feather, radius)


def _distance_to_segment(point: Point, start: Point, end: Point) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length2 = dx * dx + dy * dy
    if length2 <= 0.0:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    amount = (
        (point[0] - start[0]) * dx + (point[1] - start[1]) * dy
    ) / length2
    amount = min(1.0, max(0.0, amount))
    closest = (start[0] + amount * dx, start[1] + amount * dy)
    return math.hypot(point[0] - closest[0], point[1] - closest[1])


def brush_stroke_coverage(
    point: Point,
    polyline: Sequence[Point],
    *,
    radius: float,
    hardness: float,
    pressure: float = 1.0,
) -> float:
    """Soft coverage from hardness*radius to radius, scaled by pressure."""
    if radius <= 0.0:
        raise ManagedMaskError("brush radius must be positive", code="MASK")
    if not 0.0 <= hardness <= 1.0:
        raise ManagedMaskError("brush hardness must be from 0 to 1", code="MASK")
    if not 0.0 <= pressure <= 1.0:
        raise ManagedMaskError("brush pressure must be from 0 to 1", code="MASK")
    if len(polyline) < 1:
        return 0.0
    if len(polyline) == 1:
        distance = math.hypot(point[0] - polyline[0][0], point[1] - polyline[0][1])
    else:
        distance = min(
            _distance_to_segment(point, polyline[index], polyline[index + 1])
            for index in range(len(polyline) - 1)
        )
    inner = hardness * radius
    if distance <= inner:
        coverage = 1.0
    elif distance >= radius:
        coverage = 0.0
    else:
        coverage = 1.0 - smoothstep(inner, radius, distance)
    return min(1.0, max(0.0, coverage * pressure))


def combine_coverages(
    coverages: Sequence[float],
    mode: str,
) -> float:
    """No leaves → empty selection (0). Union/intersection/subtraction fold left."""
    if mode not in {"union", "intersection", "subtraction"}:
        raise ManagedMaskError(f"unsupported combine mode: {mode}", code="MASK")
    if not coverages:
        return 0.0
    result = float(coverages[0])
    for value in coverages[1:]:
        if mode == "union":
            result = max(result, float(value))
        elif mode == "intersection":
            result = min(result, float(value))
        else:
            result = max(0.0, result - float(value))
    return min(1.0, max(0.0, result))


def invert_coverage(coverage: float) -> float:
    if not 0.0 <= coverage <= 1.0:
        raise ManagedMaskError("coverage must be from 0 to 1", code="MASK")
    return 1.0 - coverage


def no_selection_coverage() -> float:
    """Absent selection means full coverage."""
    return 1.0


def point_in_polygon(point: Point, vertices: Sequence[Point]) -> bool:
    """Even-odd fill rule for a closed polygon (issue #527)."""
    if len(vertices) < 3:
        return False
    x, y = point
    inside = False
    previous = vertices[-1]
    for current in vertices:
        xi, yi = current
        xj, yj = previous
        if (yi > y) != (yj > y):
            # Avoid divide-by-zero on horizontal edges (even-odd skips them).
            if yj != yi and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        previous = current
    return inside


def distance_to_polygon_edges(point: Point, vertices: Sequence[Point]) -> float:
    """Minimum distance to any edge of a closed polygon."""
    if len(vertices) < 2:
        return math.hypot(point[0] - vertices[0][0], point[1] - vertices[0][1]) if vertices else 0.0
    best = float("inf")
    count = len(vertices)
    for index in range(count):
        start = vertices[index]
        end = vertices[(index + 1) % count]
        best = min(best, _distance_to_segment(point, start, end))
    return best


def polygon_coverage(
    point: Point,
    vertices: Sequence[Point],
    feather: float,
    *,
    closed: bool = True,
) -> float:
    """Filled closed polygon with optional smoothstep feather band (#527).

    Even-odd interior is full coverage. Feather expands a soft band outside the
    boundary (and softens the hard edge). Open paths (closed=False) have zero
    coverage — callers must close before fill.
    """
    if feather < 0.0:
        raise ManagedMaskError("feather must be at least zero", code="MASK")
    if not closed or len(vertices) < 3:
        return 0.0
    inside = point_in_polygon(point, vertices)
    if feather == 0.0:
        return 1.0 if inside else 0.0
    dist = distance_to_polygon_edges(point, vertices)
    # Signed distance: negative inside, positive outside (linear-matte family).
    signed = -dist if inside else dist
    return 1.0 - smoothstep(-feather / 2.0, feather / 2.0, signed)


def stamp_brush_stroke_coverage(
    width: int,
    height: int,
    polyline: Sequence[Point],
    *,
    radius: float,
    hardness: float,
    pressure: float = 1.0,
    out: list[float] | None = None,
    combine: str = "union",
) -> list[float]:
    """Rasterize one soft brush stroke into a row-major weight buffer (#525).

    Stamps soft discs along the polyline. Matches ``brush_stroke_coverage``
    within a documented feather-band tolerance (see discovery note). Analytic
    ``brush_stroke_coverage`` remains the pointwise reference for evaluate.
    """
    if width <= 0 or height <= 0:
        raise ManagedMaskError("raster size must be positive", code="MASK")
    if radius <= 0.0:
        raise ManagedMaskError("brush radius must be positive", code="MASK")
    if not 0.0 <= hardness <= 1.0:
        raise ManagedMaskError("brush hardness must be from 0 to 1", code="MASK")
    if not 0.0 <= pressure <= 1.0:
        raise ManagedMaskError("brush pressure must be from 0 to 1", code="MASK")
    buf = out if out is not None else [0.0] * (width * height)
    if len(polyline) < 1:
        return buf

    def _combine(previous: float, value: float) -> float:
        if combine == "union":
            return max(previous, value)
        if combine == "intersection":
            return min(previous, value) if previous > 0.0 else value
        # subtraction against existing buffer
        return max(0.0, previous - value)

    inner = hardness * radius
    # Sample the polyline in UV space (same metric as brush_stroke_coverage).
    samples: list[Point] = []
    if len(polyline) == 1:
        samples.append((float(polyline[0][0]), float(polyline[0][1])))
    else:
        for index in range(len(polyline) - 1):
            x0, y0 = float(polyline[index][0]), float(polyline[index][1])
            x1, y1 = float(polyline[index + 1][0]), float(polyline[index + 1][1])
            seg_len = math.hypot(x1 - x0, y1 - y0)
            step = max(1e-4, radius * 0.2)
            count = max(1, int(seg_len / step) + 1)
            for s in range(count + 1):
                t = s / count
                samples.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))

    # Pixel pad from UV radius (cover anisotropic aspect).
    pad_x = int(radius * width) + 2
    pad_y = int(radius * height) + 2
    for cu, cv in samples:
        cx = cu * width
        cy = cv * height
        x0 = max(0, int(cx) - pad_x)
        x1 = min(width - 1, int(cx) + pad_x)
        y0 = max(0, int(cy) - pad_y)
        y1 = min(height - 1, int(cy) + pad_y)
        for y in range(y0, y1 + 1):
            row = y * width
            v = (y + 0.5) / height
            for x in range(x0, x1 + 1):
                u = (x + 0.5) / width
                distance = math.hypot(u - cu, v - cv)
                if distance <= inner:
                    coverage = pressure
                elif distance >= radius:
                    continue
                else:
                    coverage = pressure * (1.0 - smoothstep(inner, radius, distance))
                idx = row + x
                buf[idx] = _combine(buf[idx], coverage)
    return buf


def step_blend(step_input: Rgb, processed: Rgb, mix: float, coverage: float) -> Rgb:
    if not 0.0 <= mix <= 1.0 or not 0.0 <= coverage <= 1.0:
        raise ManagedMaskError("mix and coverage must be from 0 to 1", code="MASK")
    factor = mix * coverage
    return (
        step_input[0] + factor * (processed[0] - step_input[0]),
        step_input[1] + factor * (processed[1] - step_input[1]),
        step_input[2] + factor * (processed[2] - step_input[2]),
    )
