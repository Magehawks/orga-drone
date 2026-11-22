"""NumPy mask raster parity and warm cache (#552)."""

from __future__ import annotations

import os
import time

import pytest

from orga_drone.studio_managed_masks import polygon_coverage
from orga_drone.studio_managed_raster_numpy import (
    NUMPY_POLYGON_PARITY_MAX_ABS,
    numpy_raster_enabled,
    rasterize_polygon_coverage_numpy,
)
from orga_drone.studio_managed_selection import (
    clear_mask_raster_cache,
    rasterize_mask_coverage,
)


SQUARE = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]


@pytest.fixture(autouse=True)
def _reset_mask_cache() -> None:
    clear_mask_raster_cache()
    yield
    clear_mask_raster_cache()


def test_numpy_backend_respects_python_force(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORGA_MASK_RASTER_BACKEND", "python")
    assert numpy_raster_enabled() is False
    monkeypatch.setenv("ORGA_MASK_RASTER_BACKEND", "auto")
    assert numpy_raster_enabled() is True


def test_numpy_polygon_matches_python_oracle_roi() -> None:
    pytest.importorskip("numpy")
    width, height = 64, 48
    feather = 0.08
    os.environ["ORGA_MASK_RASTER_BACKEND"] = "numpy"
    clear_mask_raster_cache()
    np_buf = rasterize_polygon_coverage_numpy(
        width, height, SQUARE, feather, closed=True
    )
    max_abs = 0.0
    mean_acc = 0.0
    count = 0
    for y in range(height):
        for x in range(width):
            uv = ((x + 0.5) / width, (y + 0.5) / height)
            expected = polygon_coverage(uv, SQUARE, feather, closed=True)
            got = np_buf[y * width + x]
            delta = abs(got - expected)
            max_abs = max(max_abs, delta)
            mean_acc += delta
            count += 1
    mean_abs = mean_acc / count
    assert max_abs <= NUMPY_POLYGON_PARITY_MAX_ABS
    assert mean_abs <= NUMPY_POLYGON_PARITY_MAX_ABS


def test_rasterize_mask_uses_numpy_and_matches_python_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("numpy")
    leaf = {
        "type": "polygon",
        "points": [[0.15, 0.2], [0.85, 0.18], [0.7, 0.85], [0.2, 0.75]],
        "feather": 0.05,
        "closed": True,
    }
    mask = {"combine": "union", "leaves": [leaf]}
    width, height = 80, 60
    monkeypatch.setenv("ORGA_MASK_RASTER_CACHE", "0")
    monkeypatch.setenv("ORGA_MASK_RASTER_BACKEND", "numpy")
    clear_mask_raster_cache()
    fast = rasterize_mask_coverage(mask, width=width, height=height)
    monkeypatch.setenv("ORGA_MASK_RASTER_BACKEND", "python")
    clear_mask_raster_cache()
    slow = rasterize_mask_coverage(mask, width=width, height=height)
    max_abs = max(abs(a - b) for a, b in zip(fast, slow, strict=True))
    assert max_abs <= NUMPY_POLYGON_PARITY_MAX_ABS


def test_mask_raster_cache_misses_after_backend_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Oracle env must not reuse a NumPy warm entry without clearing the LRU."""
    pytest.importorskip("numpy")
    mask = {
        "combine": "union",
        "leaves": [
            {
                "type": "polygon",
                "points": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]],
                "feather": 0.04,
                "closed": True,
            }
        ],
    }
    width, height = 64, 48
    monkeypatch.setenv("ORGA_MASK_RASTER_CACHE", "1")
    monkeypatch.setenv("ORGA_MASK_RASTER_BACKEND", "numpy")
    clear_mask_raster_cache()
    numpy_hit = rasterize_mask_coverage(mask, width=width, height=height)
    # No clear_mask_raster_cache(): backend token must force a miss.
    monkeypatch.setenv("ORGA_MASK_RASTER_BACKEND", "python")
    python_hit = rasterize_mask_coverage(mask, width=width, height=height)
    max_abs = max(abs(a - b) for a, b in zip(numpy_hit, python_hit, strict=True))
    assert max_abs <= NUMPY_POLYGON_PARITY_MAX_ABS
    # Distinct cache keys: warm NumPy entry remains, Python path still populates.
    monkeypatch.setenv("ORGA_MASK_RASTER_BACKEND", "numpy")
    assert rasterize_mask_coverage(mask, width=width, height=height) == numpy_hit


def test_warm_mask_raster_cache_skips_recompute(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("numpy")
    mask = {
        "combine": "union",
        "leaves": [
            {
                "type": "polygon",
                "points": [[0.3, 0.3], [0.7, 0.3], [0.7, 0.7], [0.3, 0.7]],
                "feather": 0.02,
                "closed": True,
            }
        ],
    }
    monkeypatch.setenv("ORGA_MASK_RASTER_BACKEND", "numpy")
    monkeypatch.setenv("ORGA_MASK_RASTER_CACHE", "1")
    clear_mask_raster_cache()
    width, height = 120, 160
    t0 = time.perf_counter()
    first = rasterize_mask_coverage(mask, width=width, height=height)
    cold = time.perf_counter() - t0
    t1 = time.perf_counter()
    second = rasterize_mask_coverage(mask, width=width, height=height)
    warm = time.perf_counter() - t1
    assert first == second
    # Warm hit should be far cheaper than cold NumPy fill on this size.
    assert warm < cold * 0.5 or warm < 0.005


def test_hard_polygon_interior_still_one() -> None:
    pytest.importorskip("numpy")
    os.environ["ORGA_MASK_RASTER_BACKEND"] = "numpy"
    clear_mask_raster_cache()
    buf = rasterize_polygon_coverage_numpy(40, 40, SQUARE, 0.0, closed=True)
    assert buf[20 * 40 + 20] == pytest.approx(1.0)
    assert buf[0] == pytest.approx(0.0)
