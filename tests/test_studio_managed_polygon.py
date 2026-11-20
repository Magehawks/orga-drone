"""Polygon leaf coverage and raster (#527)."""

from __future__ import annotations

from orga_drone.studio_managed_apply import apply_managed_grade_image
from orga_drone.studio_managed_masks import point_in_polygon, polygon_coverage
from orga_drone.studio_managed_selection import (
    evaluate_selection,
    leaf_coverage,
    rasterize_selection_coverage,
)


SQUARE = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]


def test_point_in_polygon_even_odd() -> None:
    assert point_in_polygon((0.5, 0.5), [(a, b) for a, b in SQUARE])
    assert not point_in_polygon((0.05, 0.05), [(a, b) for a, b in SQUARE])


def test_polygon_coverage_hard_and_feather() -> None:
    verts = [(a, b) for a, b in SQUARE]
    assert polygon_coverage((0.5, 0.5), verts, 0.0) == 1.0
    assert polygon_coverage((0.05, 0.05), verts, 0.0) == 0.0
    soft = polygon_coverage((0.18, 0.5), verts, 0.1)
    assert 0.0 < soft < 1.0


def test_polygon_leaf_and_raster_match() -> None:
    leaf = {"type": "polygon", "points": SQUARE, "feather": 0.0, "closed": True}
    selection = {
        "id": "sel-poly",
        "invert": False,
        "mask": {"combine": "union", "leaves": [leaf]},
        "qualifier": {"type": "none"},
    }
    width, height = 40, 40
    raster = rasterize_selection_coverage(selection, width=width, height=height)
    for y in range(height):
        for x in range(width):
            uv = ((x + 0.5) / width, (y + 0.5) / height)
            expected = evaluate_selection(selection, point=uv, rgb=(0.5, 0.5, 0.5))
            assert abs(raster[y * width + x] - expected) < 1e-9
    assert leaf_coverage((0.5, 0.5), leaf) == 1.0


def test_open_polygon_has_zero_coverage() -> None:
    leaf = {"type": "polygon", "points": SQUARE, "feather": 0.0, "closed": False}
    assert leaf_coverage((0.5, 0.5), leaf) == 0.0


def test_polygon_grade_desaturates_interior() -> None:
    grade = {
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
                            "feather": 0.0,
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
    width = height = 32
    pixels = [[(1.0, 0.0, 0.0) for _ in range(width)] for _ in range(height)]
    out = apply_managed_grade_image(pixels, grade, lattice_domain="encoded-bt709")
    # Center of square should be gray; corner outside stays red.
    center = out[16][16]
    assert abs(center[0] - center[1]) < 1e-6
    assert abs(center[1] - center[2]) < 1e-6
    corner = out[0][0]
    assert corner[0] > 0.9 and corner[1] < 0.1
