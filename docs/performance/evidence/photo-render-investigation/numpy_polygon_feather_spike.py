#!/usr/bin/env python3
"""Spike: NumPy/Pillow polygon fill vs pure-Python feather distance (#551)."""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent
GRADE = json.loads((OUT / "neon174-grade.json").read_text(encoding="utf-8"))


def points_from_grade() -> list[tuple[float, float]]:
    for sel in GRADE["selections"]:
        for leaf in sel["mask"]["leaves"]:
            if leaf["type"] == "polygon":
                return [(float(p[0]), float(p[1])) for p in leaf["points"]]
    raise SystemExit("no polygon")


def pure_python_feather(w: int, h: int, pts: list[tuple[float, float]], feather: float) -> float:
    from orga_drone.studio_managed_masks import polygon_coverage

    t0 = time.perf_counter()
    total = 0.0
    for y in range(h):
        v = (y + 0.5) / h
        for x in range(w):
            u = (x + 0.5) / w
            total += polygon_coverage((u, v), pts, closed=True, feather=feather)
    _ = total
    return time.perf_counter() - t0


def numpy_fill_distance(w: int, h: int, pts: list[tuple[float, float]], feather: float) -> float:
    """Approximate feather via binary fill + EDT (not bit-identical to smoothstep)."""
    t0 = time.perf_counter()
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    xy = [(p[0] * (w - 1), p[1] * (h - 1)) for p in pts]
    draw.polygon(xy, outline=255, fill=255)
    arr = np.asarray(mask, dtype=np.uint8)
    # Cheap stand-in for OpenCV distanceTransform: box-blur the mask edge.
    # Real follow-up should use cv2.distanceTransform for correct feather widths.
    soft = arr.astype(np.float64) / 255.0
    if feather > 0:
        # 3x3 mean blur as placeholder edge soften
        padded = np.pad(soft, 1, mode="edge")
        soft = (
            padded[0:-2, 0:-2]
            + padded[0:-2, 1:-1]
            + padded[0:-2, 2:]
            + padded[1:-1, 0:-2]
            + padded[1:-1, 1:-1]
            + padded[1:-1, 2:]
            + padded[2:, 0:-2]
            + padded[2:, 1:-1]
            + padded[2:, 2:]
        ) / 9.0
    _ = float(soft.mean())
    return time.perf_counter() - t0


def main() -> None:
    import sys

    sys.path.insert(0, str(OUT.parents[4] / "src"))
    pts = points_from_grade()
    # Downscale for pure-python tractability
    w, h = 282, 496  # ~1/4 linear of Neon
    feather = 0.015
    py_times = [pure_python_feather(w, h, pts, feather) for _ in range(2)]
    np_times = [numpy_fill_distance(w, h, pts, feather) for _ in range(5)]
    # Scale estimate to full Neon (16x pixels)
    scale = (1125 * 1984) / (w * h)
    report = {
        "probe_size": [w, h],
        "vertices": len(pts),
        "pure_python_median_s": statistics.median(py_times),
        "numpy_placeholder_median_s": statistics.median(np_times),
        "estimated_fullres_pure_python_s": statistics.median(py_times) * scale,
        "estimated_fullres_numpy_placeholder_s": statistics.median(np_times) * scale,
        "speedup_approx": statistics.median(py_times) / statistics.median(np_times),
        "note": "NumPy path is a fill+blur placeholder, not numerical parity with smoothstep feather.",
    }
    print(json.dumps(report, indent=2))
    (OUT / "numpy-polygon-feather-spike.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
