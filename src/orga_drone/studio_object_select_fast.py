"""NumPy/OpenCV acceleration for classical object proposal (#554)."""

from __future__ import annotations

import os
from typing import Any

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


def propose_mask_fast(
    work: Image.Image,
    *,
    seed_xy: tuple[int, int],
    tol: float,
) -> tuple[Any, float]:
    """Return uint8 mask (0/255) and coverage using OpenCV components/contours prep."""
    import cv2
    import numpy as np

    try:
        cv2.setNumThreads(1)
    except Exception:
        pass

    arr = np.asarray(work.convert("RGB"), dtype=np.uint8)
    height, width = arr.shape[0], arr.shape[1]
    sx, sy = seed_xy
    lab = _lab_approx_np(arr)
    seed = lab[sy, sx]

    # Chromatic distance field vs seed (same metric as Python flood).
    dL = 0.35 * (lab[..., 0] - seed[0])
    da = lab[..., 1] - seed[1]
    db = lab[..., 2] - seed[2]
    dist = np.sqrt(dL * dL + da * da + db * db)
    candidates = (dist <= float(tol)).astype(np.uint8) * 255

    # Keep only the connected component containing the seed.
    num, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        candidates, connectivity=4
    )
    if num <= 1:
        raise ValueError("no component")
    label = int(labels[sy, sx])
    if label == 0:
        raise ValueError("seed not in candidate mask")
    mask = (labels == label).astype(np.uint8) * 255

    # Morphological close (5x5) matching MaxFilter/MinFilter(5).
    kernel = np.ones((5, 5), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    # Recompute largest / seed component after close.
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
    if num <= 1:
        raise ValueError("empty after close")
    # Prefer component containing seed; else largest non-background.
    label = int(labels[sy, sx])
    if label == 0:
        areas = stats[1:, cv2.CC_STAT_AREA]
        label = 1 + int(np.argmax(areas))
    mask = (labels == label).astype(np.uint8) * 255
    coverage = float(np.count_nonzero(mask)) / float(width * height)
    return mask, coverage


def contour_points_uv(
    mask: Any,
    *,
    max_points: int,
) -> list[list[float]]:
    """Extract a simplified closed UV polygon from a binary mask."""
    import cv2

    height, width = mask.shape[:2]
    contours, _hierarchy = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    if not contours:
        raise ValueError("no contour")
    contour = max(contours, key=cv2.contourArea)
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
