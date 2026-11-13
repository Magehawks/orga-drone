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
    radial_coverage,
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
RASTERIZER_VERSION = "selection-raster-v1"


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
    """Coverage for one linear, radial or brush leaf at a normalized source point."""
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
        coverages: list[float] = []
        for stroke in strokes:
            if not isinstance(stroke, Mapping):
                raise ManagedSelectionError("brush stroke must be an object", code="SELECTION")
            polyline = _as_points(stroke.get("points") or (), label="brush.points")
            radius = float(stroke.get("radius", 0.05) or 0.05)
            hardness = float(stroke.get("hardness", 0.5) if stroke.get("hardness") is not None else 0.5)
            pressure = float(stroke.get("pressure", 1.0) if stroke.get("pressure") is not None else 1.0)
            coverages.append(
                brush_stroke_coverage(
                    point,
                    polyline,
                    radius=radius,
                    hardness=hardness,
                    pressure=pressure,
                )
            )
        return combine_coverages(coverages, mode)
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


__all__ = [
    "ManagedSelectionError",
    "RASTERIZER_VERSION",
    "evaluate_selection",
    "leaf_coverage",
    "mask_coverage",
    "qualifier_coverage",
    "selection_by_id",
]
