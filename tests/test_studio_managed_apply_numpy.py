"""NumPy managed apply parity (#553)."""

from __future__ import annotations

import pytest

from orga_drone.studio_managed_apply import apply_managed_grade_image
from orga_drone.studio_managed_apply_numpy import (
    NUMPY_APPLY_PARITY_MAX_ABS,
    NUMPY_APPLY_PARITY_MEAN_ABS,
)
from orga_drone.studio_managed_selection import clear_mask_raster_cache


SQUARE = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]


def _grade() -> dict:
    return {
        "schema_version": 1,
        "evaluator": "managed-sdr-v1",
        "revision": 1,
        "input": {"profile": "bt709-sdr", "technical_lut": None},
        "working": "linear-bt709",
        "steps": [
            {
                "id": "hsl",
                "type": "managed-hsl-v1",
                "enabled": True,
                "mix": 1.0,
                "selection_id": "sel-poly",
                "params": {"hue": 0, "saturation": 0.0, "lightness": 0},
            }
        ],
        "selections": [
            {
                "id": "sel-poly",
                "invert": False,
                "mask": {
                    "combine": "union",
                    "leaves": [
                        {
                            "type": "polygon",
                            "points": SQUARE,
                            "feather": 0.05,
                            "closed": True,
                        }
                    ],
                },
                "qualifier": {"type": "none"},
            }
        ],
        "animation": [],
        "output": {"profile": "bt709-sdr", "gamut": "clip"},
        "extensions": {},
    }


@pytest.fixture(autouse=True)
def _reset() -> None:
    clear_mask_raster_cache()
    yield
    clear_mask_raster_cache()


def test_numpy_apply_backend_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from orga_drone.studio_managed_apply_numpy import numpy_apply_enabled

    monkeypatch.setenv("ORGA_MANAGED_APPLY_BACKEND", "python")
    assert numpy_apply_enabled() is False
    monkeypatch.setenv("ORGA_MANAGED_APPLY_BACKEND", "auto")
    assert numpy_apply_enabled() is True


def test_numpy_apply_matches_python_oracle(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("numpy")
    width = height = 48
    pixels = [[(1.0, 0.2, 0.1) for _ in range(width)] for _ in range(height)]
    grade = _grade()
    monkeypatch.setenv("ORGA_MASK_RASTER_CACHE", "0")
    monkeypatch.setenv("ORGA_MANAGED_APPLY_BACKEND", "python")
    clear_mask_raster_cache()
    py = apply_managed_grade_image(pixels, grade, lattice_domain="encoded-bt709")
    monkeypatch.setenv("ORGA_MANAGED_APPLY_BACKEND", "numpy")
    clear_mask_raster_cache()
    np_out = apply_managed_grade_image(pixels, grade, lattice_domain="encoded-bt709")
    max_abs = 0.0
    mean = 0.0
    count = 0
    for y in range(height):
        for x in range(width):
            for c in range(3):
                delta = abs(py[y][x][c] - np_out[y][x][c])
                max_abs = max(max_abs, delta)
                mean += delta
                count += 1
    assert max_abs <= NUMPY_APPLY_PARITY_MAX_ABS
    assert mean / count <= NUMPY_APPLY_PARITY_MEAN_ABS
