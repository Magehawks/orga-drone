"""Selection resources: mask leaves, qualifiers and coverage (#356/#357).

Selections are source-oriented. This module evaluates coverage only; grade
writes and privacy masks stay elsewhere.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from orga_drone.studio_managed_masks import (
    ManagedMaskError,
    brush_stroke_coverage,
    combine_coverages,
    invert_coverage,
    linear_coverage,
    no_selection_coverage,
    polygon_coverage,
    radial_coverage,
    stamp_brush_stroke_coverage,
)
from orga_drone.studio_managed_qualifiers import (
    ManagedQualifierError,
    hsl_qualifier,
    luma_qualifier,
    rgb_qualifier,
    selection_coverage as compose_coverage,
)

Point = tuple[float, float]
Rgb = tuple[float, float, float]
# v2: stamp-based brush raster (#525) + polygon leaf (#527).
RASTERIZER_VERSION = "selection-raster-v2"
# Max abs delta vs analytic brush_stroke_coverage in the soft band (stamps).
BRUSH_STAMP_TOLERANCE = 0.08
MAX_POLYGON_POINTS = 4096


class ManagedSelectionError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _as_point(value: object, *, label: str) -> Point:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ManagedSelectionError(f"{label} must be a point", code="SELECTION")
    try:
        return (float(value[0]), float(value[1]))
    except (TypeError, ValueError) as exc:
        raise ManagedSelectionError(f"{label} must be finite numbers", code="SELECTION") from exc


def _as_points(value: object, *, label: str) -> list[Point]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ManagedSelectionError(f"{label} must be a point list", code="SELECTION")
    return [_as_point(entry, label=label) for entry in value]


def leaf_coverage(point: Point, leaf: Mapping[str, Any]) -> float:
    """Coverage for one linear, radial, brush or polygon leaf at a source UV."""
    kind = leaf.get("type")
    if kind == "linear":
        start = _as_point(leaf.get("start"), label="linear.start")
        end = _as_point(leaf.get("end"), label="linear.end")
        feather = float(leaf.get("feather", 0.0) or 0.0)
        return linear_coverage(point, start, end, feather)
    if kind == "radial":
        center = _as_point(leaf.get("center"), label="radial.center")
        axes = _as_point(leaf.get("axes"), label="radial.axes")
        feather = float(leaf.get("feather", 0.0) or 0.0)
        return radial_coverage(point, center, axes, feather)
    if kind == "brush":
        strokes = leaf.get("strokes")
        if not isinstance(strokes, Sequence) or isinstance(strokes, (str, bytes)):
            raise ManagedSelectionError("brush.strokes must be a list", code="SELECTION")
        if not strokes:
            return 0.0
        mode = str(leaf.get("combine", "union") or "union")
        add_coverages: list[float] = []
        subtract_strokes: list[Mapping[str, Any]] = []
        for stroke in strokes:
            if not isinstance(stroke, Mapping):
                raise ManagedSelectionError("brush stroke must be an object", code="SELECTION")
            if str(stroke.get("mode", "add") or "add") == "subtract":
                subtract_strokes.append(stroke)
                continue
            polyline = _as_points(stroke.get("points") or (), label="brush.points")
            radius = float(stroke.get("radius", 0.05) or 0.05)
            hardness = float(
                stroke.get("hardness", 0.5) if stroke.get("hardness") is not None else 0.5
            )
            pressure = float(
                stroke.get("pressure", 1.0) if stroke.get("pressure") is not None else 1.0
            )
            add_coverages.append(
                brush_stroke_coverage(
                    point,
                    polyline,
                    radius=radius,
                    hardness=hardness,
                    pressure=pressure,
                )
            )
        result = combine_coverages(add_coverages, mode) if add_coverages else 0.0
        for stroke in subtract_strokes:
            polyline = _as_points(stroke.get("points") or (), label="brush.points")
            radius = float(stroke.get("radius", 0.05) or 0.05)
            hardness = float(
                stroke.get("hardness", 0.5) if stroke.get("hardness") is not None else 0.5
            )
            pressure = float(
                stroke.get("pressure", 1.0) if stroke.get("pressure") is not None else 1.0
            )
            result = max(
                0.0,
                result
                - brush_stroke_coverage(
                    point,
                    polyline,
                    radius=radius,
                    hardness=hardness,
                    pressure=pressure,
                ),
            )
        return result
    if kind == "polygon":
        points = _as_points(leaf.get("points") or (), label="polygon.points")
        if len(points) > MAX_POLYGON_POINTS:
            raise ManagedSelectionError(
                f"polygon.points exceeds {MAX_POLYGON_POINTS}",
                code="SELECTION",
            )
        feather = float(leaf.get("feather", 0.0) or 0.0)
        closed = bool(leaf.get("closed", True))
        return polygon_coverage(point, points, feather, closed=closed)
    raise ManagedSelectionError(f"unsupported mask leaf: {kind}", code="SELECTION")


def mask_coverage(point: Point, mask: Mapping[str, Any] | None) -> float:
    """Ordered leaves combined by union/intersection/subtraction.

    ``mask is None`` means no spatial constraint (full coverage). An empty
    mask object or empty ``leaves`` list is an empty selection (zero).
    """
    if mask is None:
        return no_selection_coverage()
    if "leaves" not in mask:
        return 0.0
    leaves = mask.get("leaves")
    if not isinstance(leaves, Sequence) or isinstance(leaves, (str, bytes)):
        raise ManagedSelectionError("mask.leaves must be a list", code="SELECTION")
    if not leaves:
        return 0.0
    mode = str(mask.get("combine", "union") or "union")
    coverages = []
    for leaf in leaves:
        if not isinstance(leaf, Mapping):
            raise ManagedSelectionError("mask leaf must be an object", code="SELECTION")
        coverages.append(leaf_coverage(point, leaf))
    return combine_coverages(coverages, mode)


def qualifier_coverage(rgb: Rgb, qualifier: Mapping[str, Any] | None) -> float:
    """Pointwise qualifier on the step's encoded BT.709 input. None → full."""
    if qualifier is None:
        return 1.0
    kind = qualifier.get("type")
    if kind in (None, "", "none"):
        return 1.0
    if kind == "rgb":
        channels_raw = qualifier.get("channels")
        if not isinstance(channels_raw, Sequence) or len(channels_raw) != 3:
            raise ManagedSelectionError("rgb qualifier needs three intervals", code="SELECTION")
        channels: list[tuple[float, float]] = []
        for entry in channels_raw:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                raise ManagedSelectionError("rgb interval malformed", code="SELECTION")
            channels.append((float(entry[0]), float(entry[1])))
        return rgb_qualifier(rgb, (channels[0], channels[1], channels[2]))
    if kind == "hsl":
        hue = qualifier.get("hue")
        saturation = qualifier.get("saturation")
        lightness = qualifier.get("lightness")
        return hsl_qualifier(
            rgb,
            hue=(float(hue[0]), float(hue[1])) if isinstance(hue, (list, tuple)) else None,
            saturation=(
                (float(saturation[0]), float(saturation[1]))
                if isinstance(saturation, (list, tuple))
                else None
            ),
            lightness=(
                (float(lightness[0]), float(lightness[1]))
                if isinstance(lightness, (list, tuple))
                else None
            ),
        )
    if kind == "luma":
        inner = float(qualifier.get("inner", 0.5) if qualifier.get("inner") is not None else 0.5)
        outer = float(qualifier.get("outer", 0.5) if qualifier.get("outer") is not None else inner)
        return luma_qualifier(rgb, inner, outer)
    raise ManagedSelectionError(f"unsupported qualifier: {kind}", code="SELECTION")


def evaluate_selection(
    selection: Mapping[str, Any] | None,
    *,
    point: Point | None,
    rgb: Rgb,
) -> float:
    """Full selection coverage = mask * qualifier, then optional invert.

    Absent selection → full coverage. Empty mask leaves → zero before invert.
    Spatial leaves require a normalized source ``point``; qualifier-only
    selections may omit it.
    """
    if selection is None:
        return no_selection_coverage()
    mask = selection.get("mask")
    mask_map: Mapping[str, Any] | None
    if mask is None:
        mask_map = None
    elif isinstance(mask, Mapping):
        mask_map = mask
    else:
        raise ManagedSelectionError("selection.mask must be an object", code="SELECTION")

    leaves = None if mask_map is None else mask_map.get("leaves")
    needs_point = (
        mask_map is not None
        and "leaves" in mask_map
        and isinstance(leaves, Sequence)
        and not isinstance(leaves, (str, bytes))
        and len(leaves) > 0
    )
    if needs_point and point is None:
        raise ManagedSelectionError(
            "spatial mask requires a source point",
            code="SELECTION",
        )

    try:
        mask_value = mask_coverage(point or (0.0, 0.0), mask_map)
        qualifier = selection.get("qualifier")
        if qualifier is not None and not isinstance(qualifier, Mapping):
            raise ManagedSelectionError("selection.qualifier must be an object", code="SELECTION")
        qualifier_map: Mapping[str, Any] | None = (
            qualifier if isinstance(qualifier, Mapping) else None
        )
        qual_value = qualifier_coverage(rgb, qualifier_map)
        invert = bool(selection.get("invert", False))
        return compose_coverage(mask_value, qual_value, invert=invert)
    except (ManagedMaskError, ManagedQualifierError) as exc:
        code = getattr(exc, "code", "SELECTION")
        raise ManagedSelectionError(str(exc), code=str(code)) from exc


def selection_by_id(
    selections: Sequence[Mapping[str, Any]] | None,
    selection_id: str | None,
) -> Mapping[str, Any] | None:
    if not selection_id:
        return None
    if not selections:
        raise ManagedSelectionError(
            f"dangling selection reference: {selection_id}",
            code="SELECTION",
        )
    for entry in selections:
        if isinstance(entry, Mapping) and entry.get("id") == selection_id:
            return entry
    raise ManagedSelectionError(
        f"dangling selection reference: {selection_id}",
        code="SELECTION",
    )


def invert_selection_coverage(coverage: float) -> float:
    return invert_coverage(coverage)


def _brush_leaf_pixel_bounds(
    leaf: Mapping[str, Any],
    *,
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    """Inclusive pixel bounds covering all strokes (+ radius), or None if empty."""
    strokes = leaf.get("strokes")
    if not isinstance(strokes, Sequence) or isinstance(strokes, (str, bytes)) or not strokes:
        return None
    min_x = 1.0
    min_y = 1.0
    max_x = 0.0
    max_y = 0.0
    found = False
    for stroke in strokes:
        if not isinstance(stroke, Mapping):
            continue
        try:
            polyline = _as_points(stroke.get("points") or (), label="brush.points")
            radius = float(stroke.get("radius", 0.05) or 0.05)
        except ManagedSelectionError:
            continue
        if not polyline or radius <= 0.0:
            continue
        found = True
        for px, py in polyline:
            min_x = min(min_x, px - radius)
            max_x = max(max_x, px + radius)
            min_y = min(min_y, py - radius)
            max_y = max(max_y, py + radius)
    if not found:
        return None
    x0 = max(0, int(min_x * width) - 1)
    x1 = min(width - 1, int(max_x * width) + 1)
    y0 = max(0, int(min_y * height) - 1)
    y1 = min(height - 1, int(max_y * height) + 1)
    if x1 < x0 or y1 < y0:
        return None
    return x0, y0, x1, y1


def _polygon_leaf_pixel_bounds(
    leaf: Mapping[str, Any],
    *,
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    points = leaf.get("points")
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes)) or len(points) < 3:
        return None
    try:
        verts = _as_points(points, label="polygon.points")
        feather = float(leaf.get("feather", 0.0) or 0.0)
    except ManagedSelectionError:
        return None
    xs = [p[0] for p in verts]
    ys = [p[1] for p in verts]
    pad = max(0.0, feather)
    x0 = max(0, int((min(xs) - pad) * width) - 1)
    x1 = min(width - 1, int((max(xs) + pad) * width) + 1)
    y0 = max(0, int((min(ys) - pad) * height) - 1)
    y1 = min(height - 1, int((max(ys) + pad) * height) + 1)
    if x1 < x0 or y1 < y0:
        return None
    return x0, y0, x1, y1


def _rasterize_brush_leaf_stamped(
    leaf: Mapping[str, Any],
    *,
    width: int,
    height: int,
) -> list[float]:
    """Stamp soft brush discs once per leaf (#525)."""
    strokes = leaf.get("strokes")
    out = [0.0] * (width * height)
    if not isinstance(strokes, Sequence) or isinstance(strokes, (str, bytes)):
        raise ManagedSelectionError("brush.strokes must be a list", code="SELECTION")
    mode = str(leaf.get("combine", "union") or "union")
    add_strokes: list[Mapping[str, Any]] = []
    sub_strokes: list[Mapping[str, Any]] = []
    for stroke in strokes:
        if not isinstance(stroke, Mapping):
            raise ManagedSelectionError("brush stroke must be an object", code="SELECTION")
        if str(stroke.get("mode", "add") or "add") == "subtract":
            sub_strokes.append(stroke)
        else:
            add_strokes.append(stroke)

    def _stamp(stroke: Mapping[str, Any], *, combine: str) -> None:
        polyline = _as_points(stroke.get("points") or (), label="brush.points")
        radius = float(stroke.get("radius", 0.05) or 0.05)
        hardness = float(
            stroke.get("hardness", 0.5) if stroke.get("hardness") is not None else 0.5
        )
        pressure = float(
            stroke.get("pressure", 1.0) if stroke.get("pressure") is not None else 1.0
        )
        try:
            stamp_brush_stroke_coverage(
                width,
                height,
                polyline,
                radius=radius,
                hardness=hardness,
                pressure=pressure,
                out=out,
                combine=combine,
            )
        except ManagedMaskError as exc:
            raise ManagedSelectionError(str(exc), code="SELECTION") from exc

    for stroke in add_strokes:
        _stamp(stroke, combine=mode)
    for stroke in sub_strokes:
        _stamp(stroke, combine="subtraction")
    return out


def rasterize_mask_coverage(
    mask: Mapping[str, Any] | None,
    *,
    width: int,
    height: int,
) -> list[float]:
    """Row-major spatial mask weights in ``[0, 1]`` (no qualifier / invert).

    Single brush or polygon leaves use ROI + stamp/analytic fill. Mixed leaves
    fall back to a full-frame analytic pass. Empty / absent masks match
    ``mask_coverage`` semantics.
    """
    if width <= 0 or height <= 0:
        raise ManagedSelectionError("raster size must be positive", code="SELECTION")
    size = width * height
    if mask is None:
        return [1.0] * size
    if "leaves" not in mask:
        return [0.0] * size
    leaves = mask.get("leaves")
    if not isinstance(leaves, Sequence) or isinstance(leaves, (str, bytes)):
        raise ManagedSelectionError("mask.leaves must be a list", code="SELECTION")
    if not leaves:
        return [0.0] * size

    # Fast path: one brush leaf → stamp raster (#525).
    if len(leaves) == 1 and isinstance(leaves[0], Mapping) and leaves[0].get("type") == "brush":
        return _rasterize_brush_leaf_stamped(leaves[0], width=width, height=height)

    # Fast path: one polygon leaf → bbox analytic fill (#527).
    if len(leaves) == 1 and isinstance(leaves[0], Mapping) and leaves[0].get("type") == "polygon":
        out = [0.0] * size
        box = _polygon_leaf_pixel_bounds(leaves[0], width=width, height=height)
        if box is None:
            return out
        x0, y0, x1, y1 = box
        for y in range(y0, y1 + 1):
            row = y * width
            v = (y + 0.5) / height
            for x in range(x0, x1 + 1):
                u = (x + 0.5) / width
                out[row + x] = leaf_coverage((u, v), leaves[0])
        return out

    brush_only = True
    bounds: list[tuple[int, int, int, int]] = []
    for leaf in leaves:
        if not isinstance(leaf, Mapping):
            raise ManagedSelectionError("mask leaf must be an object", code="SELECTION")
        kind = leaf.get("type")
        if kind == "brush":
            box = _brush_leaf_pixel_bounds(leaf, width=width, height=height)
            if box is not None:
                bounds.append(box)
        elif kind == "polygon":
            brush_only = False
            box = _polygon_leaf_pixel_bounds(leaf, width=width, height=height)
            if box is not None:
                bounds.append(box)
        else:
            brush_only = False
            bounds = []
            break

    out = [0.0] * size
    if bounds and (brush_only or all(
        isinstance(leaf, Mapping) and leaf.get("type") in {"brush", "polygon"}
        for leaf in leaves
    )):
        x0 = min(b[0] for b in bounds)
        y0 = min(b[1] for b in bounds)
        x1 = max(b[2] for b in bounds)
        y1 = max(b[3] for b in bounds)
        # Multi-brush: stamp each then combine is complex; use analytic ROI.
        if brush_only and all(
            isinstance(leaf, Mapping) and leaf.get("type") == "brush" for leaf in leaves
        ):
            # Stamp each brush leaf and union.
            mode = str(mask.get("combine", "union") or "union")
            first = True
            for leaf in leaves:
                if not isinstance(leaf, Mapping):
                    continue
                stamped = _rasterize_brush_leaf_stamped(leaf, width=width, height=height)
                if first:
                    out = stamped
                    first = False
                    continue
                if mode == "union":
                    out = [max(a, b) for a, b in zip(out, stamped, strict=True)]
                elif mode == "intersection":
                    out = [min(a, b) for a, b in zip(out, stamped, strict=True)]
                else:
                    out = [max(0.0, a - b) for a, b in zip(out, stamped, strict=True)]
            return out
        for y in range(y0, y1 + 1):
            row = y * width
            v = (y + 0.5) / height
            for x in range(x0, x1 + 1):
                u = (x + 0.5) / width
                out[row + x] = mask_coverage((u, v), mask)
        return out

    for y in range(height):
        row = y * width
        v = (y + 0.5) / height
        for x in range(width):
            u = (x + 0.5) / width
            out[row + x] = mask_coverage((u, v), mask)
    return out


def rasterize_selection_coverage(
    selection: Mapping[str, Any] | None,
    *,
    width: int,
    height: int,
) -> list[float]:
    """Spatial mask raster with invert applied. Qualifiers are not baked here."""
    if selection is None:
        return [1.0] * (width * height)
    mask = selection.get("mask")
    mask_map: Mapping[str, Any] | None
    if mask is None:
        mask_map = None
    elif isinstance(mask, Mapping):
        mask_map = mask
    else:
        raise ManagedSelectionError("selection.mask must be an object", code="SELECTION")
    qualifier = selection.get("qualifier")
    if qualifier is not None and not isinstance(qualifier, Mapping):
        raise ManagedSelectionError("selection.qualifier must be an object", code="SELECTION")
    if isinstance(qualifier, Mapping) and str(qualifier.get("type") or "") not in {
        "",
        "none",
    }:
        # Qualifier depends on RGB — callers must combine per pixel.
        raise ManagedSelectionError(
            "qualifier selections cannot be fully rasterized",
            code="SELECTION",
        )
    weights = rasterize_mask_coverage(mask_map, width=width, height=height)
    if bool(selection.get("invert", False)):
        return [invert_coverage(value) for value in weights]
    return weights


__all__ = [
    "BRUSH_STAMP_TOLERANCE",
    "MAX_POLYGON_POINTS",
    "ManagedSelectionError",
    "RASTERIZER_VERSION",
    "evaluate_selection",
    "leaf_coverage",
    "mask_coverage",
    "qualifier_coverage",
    "rasterize_mask_coverage",
    "rasterize_selection_coverage",
    "selection_by_id",
]
