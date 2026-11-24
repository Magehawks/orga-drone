"""NumPy/OpenCV acceleration for classical object proposal (#554/#550)."""

from __future__ import annotations

import os
from typing import Any, Sequence

from PIL import Image


def fast_object_select_enabled() -> bool:
    raw = os.getenv("ORGA_OBJECT_SELECT_BACKEND", "auto").strip().lower()
    if raw in {"python", "oracle", "ref", "reference"}:
        return False
    if raw in {"auto", "numpy", "opencv", ""}:
        try:
            import cv2  # noqa: F401
            import numpy as np  # noqa: F401
        except ImportError:
            return False
        return True
    return False


def _lab_approx_np(arr: Any) -> Any:
    import numpy as np

    rr = arr[..., 0].astype(np.float64) / 255.0
    gg = arr[..., 1].astype(np.float64) / 255.0
    bb = arr[..., 2].astype(np.float64) / 255.0
    L = (0.2126 * rr + 0.7152 * gg + 0.0722 * bb) * 100.0
    a = (rr - gg) * 128.0
    bch = (0.5 * (rr + gg) - bb) * 128.0
    return np.stack([L, a, bch], axis=-1)


def _component_for_seed(
    lab: Any,
    *,
    seed_xy: tuple[int, int],
    tol: float,
) -> Any:
    import cv2
    import numpy as np

    sx, sy = seed_xy
    seed = lab[sy, sx]
    dL = 0.35 * (lab[..., 0] - seed[0])
    da = lab[..., 1] - seed[1]
    db = lab[..., 2] - seed[2]
    dist = np.sqrt(dL * dL + da * da + db * db)
    candidates = (dist <= float(tol)).astype(np.uint8) * 255
    num, labels, _stats, _centroids = cv2.connectedComponentsWithStats(
        candidates, connectivity=4
    )
    if num <= 1:
        raise ValueError("no component")
    label = int(labels[sy, sx])
    if label == 0:
        raise ValueError("seed not in candidate mask")
    return (labels == label).astype(np.uint8) * 255


def _expand_mask(
    lab: Any,
    mask: Any,
    *,
    primary_xy: tuple[int, int],
    tol: float,
    passes: int,
) -> Any:
    """Grow a seed-connected mask into nearby similar colors (#550)."""
    import cv2
    import numpy as np

    if passes <= 0:
        return mask
    px, py = primary_xy
    primary = lab[py, px]
    out = mask.copy()
    kernel = np.ones((3, 3), dtype=np.uint8)
    for step in range(max(0, int(passes))):
        grow_tol = float(tol) * (1.0 + 0.12 * (step + 1))
        dL = 0.35 * (lab[..., 0] - primary[0])
        da = lab[..., 1] - primary[1]
        db = lab[..., 2] - primary[2]
        dist = np.sqrt(dL * dL + da * da + db * db)
        similar = (dist <= grow_tol).astype(np.uint8) * 255
        dilated = cv2.dilate(out, kernel, iterations=1)
        ring = cv2.bitwise_and(dilated, cv2.bitwise_not(out))
        add = cv2.bitwise_and(ring, similar)
        if not np.any(add):
            break
        out = cv2.bitwise_or(out, add)
    return out


def propose_mask_fast(
    work: Image.Image,
    *,
    seed_xy: tuple[int, int] | None = None,
    seeds_xy: Sequence[tuple[int, int]] | None = None,
    tol: float,
    expand_passes: int = 0,
) -> tuple[Any, float]:
    """Return uint8 mask (0/255) and coverage using OpenCV components/contours prep.

    Multiple seeds are unioned (each keeps its own chromatic flood). Optional
    ``expand_passes`` grows the union into nearby similar colors while staying
    connected to the primary seed region (#550).
    """
    import cv2
    import numpy as np

    try:
        cv2.setNumThreads(1)
    except Exception:
        pass

    arr = np.asarray(work.convert("RGB"), dtype=np.uint8)
    height, width = arr.shape[0], arr.shape[1]
    seeds: list[tuple[int, int]] = []
    if seeds_xy:
        for sx, sy in seeds_xy:
            ix, iy = int(sx), int(sy)
            if 0 <= ix < width and 0 <= iy < height:
                seeds.append((ix, iy))
    if seed_xy is not None:
        ix, iy = int(seed_xy[0]), int(seed_xy[1])
        if 0 <= ix < width and 0 <= iy < height and (ix, iy) not in seeds:
            seeds.insert(0, (ix, iy))
    if not seeds:
        raise ValueError("no seeds")

    lab = _lab_approx_np(arr)
    union = np.zeros((height, width), dtype=np.uint8)
    for sx, sy in seeds:
        try:
            component = _component_for_seed(lab, seed_xy=(sx, sy), tol=float(tol))
        except ValueError:
            continue
        union = np.maximum(union, component)
    if not np.any(union):
        raise ValueError("no component")

    if expand_passes > 0:
        union = _expand_mask(
            lab,
            union,
            primary_xy=seeds[0],
            tol=float(tol),
            passes=int(expand_passes),
        )

    # Morphological close (5x5) matching MaxFilter/MinFilter(5).
    kernel = np.ones((5, 5), dtype=np.uint8)
    mask = cv2.morphologyEx(union, cv2.MORPH_CLOSE, kernel)

    # Keep every component that still contains a seed (multi-seed must not
    # collapse to only the primary lobe when a gap remains after close).
    num, labels, _stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
    if num <= 1:
        raise ValueError("empty after close")
    keep = np.zeros(num, dtype=bool)
    for sx, sy in seeds:
        label = int(labels[sy, sx])
        if label > 0:
            keep[label] = True
    if not np.any(keep):
        areas = _stats[1:, cv2.CC_STAT_AREA]
        keep[1 + int(np.argmax(areas))] = True
    mask = keep[labels].astype(np.uint8) * 255
    coverage = float(np.count_nonzero(mask)) / float(width * height)
    return mask, coverage


def contour_points_uv(
    mask: Any,
    *,
    max_points: int,
) -> list[list[float]]:
    """Extract a simplified closed UV polygon from a binary mask.

    When the mask has multiple external components (multi-seed gaps), use the
    convex hull of all contour points so one polygon covers every seed lobe.
    """
    import cv2
    import numpy as np

    height, width = mask.shape[:2]
    contours, _hierarchy = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    if not contours:
        raise ValueError("no contour")
    if len(contours) == 1:
        contour = contours[0]
    else:
        stacked = np.vstack(contours)
        hull = cv2.convexHull(stacked)
        contour = hull if hull is not None and len(hull) >= 3 else max(
            contours, key=cv2.contourArea
        )
    if len(contour) < 3:
        raise ValueError("contour too small")

    # Approximate like Douglas-Peucker budget.
    epsilon = max(1.0, min(width, height) * 0.004)
    approx = contour
    for _ in range(12):
        approx = cv2.approxPolyDP(contour, epsilon, closed=True)
        if len(approx) <= max_points:
            break
        epsilon *= 1.45
    if len(approx) > max_points:
        step = max(1, len(approx) // max_points)
        approx = approx[::step][:max_points]
    if len(approx) < 3:
        raise ValueError("simplified contour too small")

    points: list[list[float]] = []
    for pt in approx.reshape(-1, 2):
        x = max(0.0, min(1.0, float(pt[0]) / float(max(1, width - 1))))
        y = max(0.0, min(1.0, float(pt[1]) / float(max(1, height - 1))))
        points.append([x, y])
    if len(points) >= 2 and points[0] == points[-1]:
        points = points[:-1]
    if len(points) < 3:
        raise ValueError("fewer than 3 points")
    return points
