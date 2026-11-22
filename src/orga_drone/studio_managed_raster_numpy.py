"""NumPy/OpenCV-accelerated mask rasterization with Python-oracle semantics (#552).

Distances and coverage stay in source UV space (same as
``studio_managed_masks.polygon_coverage``). OpenCV accelerates hard fill and
feather-band extraction; exact even-odd + edge distance run only on the band
so soft coverage matches the oracle.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping, Sequence
from typing import Any

Point = tuple[float, float]

# Max abs error vs pure-Python ``polygon_coverage`` / leaf raster (float64 path).
NUMPY_POLYGON_PARITY_MAX_ABS = 1e-9


def numpy_raster_enabled() -> bool:
    """Default on when NumPy imports; ``ORGA_MASK_RASTER_BACKEND=python`` forces oracle."""
    raw = os.getenv("ORGA_MASK_RASTER_BACKEND", "auto").strip().lower()
    if raw in {"python", "oracle", "ref", "reference"}:
        return False
    if raw in {"numpy", "auto", "opencv", ""}:
        try:
            import numpy as np  # noqa: F401
        except ImportError:
            return False
        return True
    return False


def _opencv_available() -> bool:
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False
    return True


def _smoothstep_np(edge0: float, edge1: float, value: Any) -> Any:
    import numpy as np

    if edge1 == edge0:
        raise ValueError("smoothstep edges must differ")
    amount = np.clip((value - edge0) / (edge1 - edge0), 0.0, 1.0)
    return amount * amount * (3.0 - 2.0 * amount)


def _even_odd_inside_points(
    u: Any,
    v: Any,
    vertices: Sequence[Point],
) -> Any:
    """Even-odd fill for flat or 2D UV arrays matching ``point_in_polygon``."""
    import numpy as np

    inside = np.zeros(np.shape(u), dtype=bool)
    if len(vertices) < 3:
        return inside
    count = len(vertices)
    for index in range(count):
        xj, yj = vertices[index - 1]
        xi, yi = vertices[index]
        crossing = (yi > v) != (yj > v)
        denom = yj - yi
        with np.errstate(divide="ignore", invalid="ignore"):
            x_at = (xj - xi) * (v - yi) / denom + xi
        inside ^= crossing & (u < x_at)
    return inside


def _min_edge_distance_uv_points(
    u: Any,
    v: Any,
    vertices: Sequence[Point],
) -> Any:
    """Minimum Euclidean UV distance to any closed polygon edge."""
    import numpy as np

    if len(vertices) < 2:
        if not vertices:
            return np.zeros(np.shape(u), dtype=np.float64)
        x0, y0 = vertices[0]
        return np.hypot(u - x0, v - y0)

    best = np.full(np.shape(u), np.inf, dtype=np.float64)
    count = len(vertices)
    for index in range(count):
        x0, y0 = vertices[index]
        x1, y1 = vertices[(index + 1) % count]
        dx = x1 - x0
        dy = y1 - y0
        length2 = dx * dx + dy * dy
        if length2 <= 0.0:
            dist = np.hypot(u - x0, v - y0)
        else:
            amount = np.clip(((u - x0) * dx + (v - y0) * dy) / length2, 0.0, 1.0)
            dist = np.hypot(u - (x0 + amount * dx), v - (y0 + amount * dy))
        best = np.minimum(best, dist)
    return best


def _opencv_hard_fill(
    width: int,
    height: int,
    vertices: Sequence[Point],
    *,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
) -> Any:
    """Hard polygon fill for an ROI; disagreements vs even-odd lie near edges."""
    import cv2
    import numpy as np

    roi_h = y1 - y0 + 1
    roi_w = x1 - x0 + 1
    canvas = np.zeros((roi_h, roi_w), dtype=np.uint8)
    pts = np.array(
        [[p[0] * width - x0, p[1] * height - y0] for p in vertices],
        dtype=np.float32,
    )
    pts_i = np.round(pts).astype(np.int32)
    cv2.fillPoly(canvas, [pts_i], 1, lineType=cv2.LINE_8)
    return canvas.astype(bool)


def rasterize_polygon_coverage_numpy(
    width: int,
    height: int,
    vertices: Sequence[Point],
    feather: float,
    *,
    closed: bool = True,
    x0: int = 0,
    y0: int = 0,
    x1: int | None = None,
    y1: int | None = None,
) -> list[float]:
    """Row-major polygon coverage matching ``polygon_coverage`` per pixel center."""
    import numpy as np

    if width <= 0 or height <= 0:
        raise ValueError("raster size must be positive")
    if feather < 0.0:
        raise ValueError("feather must be at least zero")

    size = width * height
    out = np.zeros(size, dtype=np.float64)
    if not closed or len(vertices) < 3:
        return out.tolist()

    xa = max(0, x0)
    ya = max(0, y0)
    xb = width - 1 if x1 is None else min(width - 1, x1)
    yb = height - 1 if y1 is None else min(height - 1, y1)
    if xb < xa or yb < ya:
        return out.tolist()

    verts = [(float(p[0]), float(p[1])) for p in vertices]
    half = feather / 2.0
    # Anisotropic pad: UV ball of radius ``half`` maps to (half*w, half*h) pixels.
    if feather == 0.0:
        pad_x = pad_y = 1
    else:
        pad_x = int(math.ceil(half * width)) + 4
        pad_y = int(math.ceil(half * height)) + 4
    xa_e = max(0, xa - pad_x)
    ya_e = max(0, ya - pad_y)
    xb_e = min(width - 1, xb + pad_x)
    yb_e = min(height - 1, yb + pad_y)

    def _uv_for_roi_indices(by: Any, bx: Any) -> tuple[Any, Any]:
        # Pixel centers in full-image UV for ROI-local nonzero indices.
        return ((bx + xa_e + 0.5) / width, (by + ya_e + 0.5) / height)

    if feather == 0.0:
        if _opencv_available():
            inside = _opencv_hard_fill(
                width, height, verts, x0=xa_e, y0=ya_e, x1=xb_e, y1=yb_e
            )
            # Exact correction on a 1px morphological ring keeps hard-mask parity.
            import cv2

            iu = np.asarray(inside, dtype=np.uint8)
            kernel = np.ones((3, 3), dtype=np.uint8)
            band = cv2.dilate(iu, kernel) != cv2.erode(iu, kernel)
            if np.any(band):
                by, bx = np.nonzero(band)
                ub, vb = _uv_for_roi_indices(by, bx)
                corrected = np.array(inside, copy=True, dtype=bool)
                corrected[by, bx] = _even_odd_inside_points(ub, vb, verts)
                inside = corrected
        else:
            xs = np.arange(xa_e, xb_e + 1, dtype=np.float64)
            ys = np.arange(ya_e, yb_e + 1, dtype=np.float64)
            u, v = np.meshgrid((xs + 0.5) / width, (ys + 0.5) / height, indexing="xy")
            inside = _even_odd_inside_points(u, v, verts)
        patch = np.asarray(inside, dtype=np.float64)
    else:
        if _opencv_available():
            import cv2

            approx = _opencv_hard_fill(
                width, height, verts, x0=xa_e, y0=ya_e, x1=xb_e, y1=yb_e
            )
            iu = np.asarray(approx, dtype=np.uint8)
            kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (2 * pad_x + 1, 2 * pad_y + 1)
            )
            band = cv2.dilate(iu, kernel) != cv2.erode(iu, kernel)
            # Morphology cannot see outside the frame; polygons that touch UV 0/1
            # need an exact strip along the image border (#552).
            if xa_e == 0:
                band[:, :pad_x] = True
            if ya_e == 0:
                band[:pad_y, :] = True
            if xb_e >= width - 1:
                band[:, -pad_x:] = True
            if yb_e >= height - 1:
                band[-pad_y:, :] = True
            patch = approx.astype(np.float64)
            if np.any(band):
                by, bx = np.nonzero(band)
                ub, vb = _uv_for_roi_indices(by, bx)
                inside_band = _even_odd_inside_points(ub, vb, verts)
                dist = _min_edge_distance_uv_points(ub, vb, verts)
                signed = np.where(inside_band, -dist, dist)
                patch[by, bx] = 1.0 - _smoothstep_np(-half, half, signed)
        else:
            xs = np.arange(xa_e, xb_e + 1, dtype=np.float64)
            ys = np.arange(ya_e, yb_e + 1, dtype=np.float64)
            u, v = np.meshgrid((xs + 0.5) / width, (ys + 0.5) / height, indexing="xy")
            inside = _even_odd_inside_points(u, v, verts)
            dist = _min_edge_distance_uv_points(u, v, verts)
            signed = np.where(inside, -dist, dist)
            patch = 1.0 - _smoothstep_np(-half, half, signed)

    # Crop expanded ROI back to the caller box before writing.
    off_y = ya - ya_e
    off_x = xa - xa_e
    patch = patch[off_y : off_y + (yb - ya + 1), off_x : off_x + (xb - xa + 1)]

    out_2d = out.reshape(height, width)
    out_2d[ya : yb + 1, xa : xb + 1] = patch
    return out.tolist()


def rasterize_linear_coverage_numpy(
    width: int,
    height: int,
    start: Point,
    end: Point,
    feather: float,
    *,
    x0: int = 0,
    y0: int = 0,
    x1: int | None = None,
    y1: int | None = None,
) -> list[float]:
    """Row-major linear matte matching ``linear_coverage``."""
    import numpy as np

    from orga_drone.studio_managed_masks import ManagedMaskError

    size = width * height
    out = np.zeros(size, dtype=np.float64)
    xa = max(0, x0)
    ya = max(0, y0)
    xb = width - 1 if x1 is None else min(width - 1, x1)
    yb = height - 1 if y1 is None else min(height - 1, y1)
    if xb < xa or yb < ya:
        return out.tolist()

    xs = np.arange(xa, xb + 1, dtype=np.float64)
    ys = np.arange(ya, yb + 1, dtype=np.float64)
    u, v = np.meshgrid((xs + 0.5) / width, (ys + 0.5) / height, indexing="xy")

    length = math.hypot(end[0] - start[0], end[1] - start[1])
    if length <= 0.0:
        raise ManagedMaskError("mask line is degenerate", code="MASK")
    distance = (
        (end[0] - start[0]) * (v - start[1]) - (end[1] - start[1]) * (u - start[0])
    ) / length
    if feather < 0.0:
        raise ManagedMaskError("feather must be at least zero", code="MASK")
    if feather == 0.0:
        patch = (distance <= 0.0).astype(np.float64)
    else:
        half = feather / 2.0
        patch = _smoothstep_np(-half, half, distance)

    out_2d = out.reshape(height, width)
    out_2d[ya : yb + 1, xa : xb + 1] = patch
    return out.tolist()


def rasterize_radial_coverage_numpy(
    width: int,
    height: int,
    center: Point,
    axes: Point,
    feather: float,
    *,
    x0: int = 0,
    y0: int = 0,
    x1: int | None = None,
    y1: int | None = None,
) -> list[float]:
    """Row-major radial matte matching ``radial_coverage``."""
    import numpy as np

    from orga_drone.studio_managed_masks import ManagedMaskError

    if axes[0] <= 0.0 or axes[1] <= 0.0:
        raise ManagedMaskError("radial axes must be positive", code="MASK")
    if feather < 0.0:
        raise ManagedMaskError("feather must be at least zero", code="MASK")

    size = width * height
    out = np.zeros(size, dtype=np.float64)
    xa = max(0, x0)
    ya = max(0, y0)
    xb = width - 1 if x1 is None else min(width - 1, x1)
    yb = height - 1 if y1 is None else min(height - 1, y1)
    if xb < xa or yb < ya:
        return out.tolist()

    xs = np.arange(xa, xb + 1, dtype=np.float64)
    ys = np.arange(ya, yb + 1, dtype=np.float64)
    u, v = np.meshgrid((xs + 0.5) / width, (ys + 0.5) / height, indexing="xy")
    radius = np.hypot((u - center[0]) / axes[0], (v - center[1]) / axes[1])
    if feather == 0.0:
        patch = (radius <= 1.0).astype(np.float64)
    else:
        patch = 1.0 - _smoothstep_np(1.0 - feather, 1.0 + feather, radius)

    out_2d = out.reshape(height, width)
    out_2d[ya : yb + 1, xa : xb + 1] = patch
    return out.tolist()


def try_rasterize_polygon_leaf(
    leaf: Mapping[str, Any],
    *,
    width: int,
    height: int,
    box: tuple[int, int, int, int] | None,
) -> list[float] | None:
    """Return NumPy raster for a polygon leaf, or None to fall back."""
    if not numpy_raster_enabled():
        return None
    points = leaf.get("points")
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
        return None
    if len(points) < 3:
        return [0.0] * (width * height)
    try:
        verts = [(float(p[0]), float(p[1])) for p in points]
        feather = float(leaf.get("feather", 0.0) or 0.0)
        closed = bool(leaf.get("closed", True))
    except (TypeError, ValueError):
        return None
    if box is None:
        x0, y0, x1, y1 = 0, 0, width - 1, height - 1
    else:
        x0, y0, x1, y1 = box
    return rasterize_polygon_coverage_numpy(
        width,
        height,
        verts,
        feather,
        closed=closed,
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
    )


__all__ = [
    "NUMPY_POLYGON_PARITY_MAX_ABS",
    "numpy_raster_enabled",
    "rasterize_linear_coverage_numpy",
    "rasterize_polygon_coverage_numpy",
    "rasterize_radial_coverage_numpy",
    "try_rasterize_polygon_leaf",
]
