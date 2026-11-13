"""Selection coverage fixtures for masks and qualifiers (#356/#357)."""

from __future__ import annotations

import pytest

from orga_drone.studio_managed_apply import (
    apply_managed_grade_image,
    apply_managed_grade_rgb,
)
from orga_drone.studio_managed_selection import (
    ManagedSelectionError,
    evaluate_selection,
    leaf_coverage,
    mask_coverage,
    qualifier_coverage,
)


def test_linear_radial_brush_leaves() -> None:
    assert leaf_coverage(
        (0.2, 0.5),
        {"type": "linear", "start": (0.0, 0.0), "end": (0.0, 1.0), "feather": 0.0},
    ) == 1.0
    assert leaf_coverage(
        (0.5, 0.5),
        {"type": "radial", "center": (0.5, 0.5), "axes": (0.25, 0.25), "feather": 0.0},
    ) == 1.0
    assert (
        leaf_coverage(
            (0.1, 0.1),
            {
                "type": "brush",
                "combine": "union",
                "strokes": [{"points": [(0.1, 0.1)], "radius": 0.2, "hardness": 1.0}],
            },
        )
        == 1.0
    )


def test_empty_mask_is_zero_and_absent_is_full() -> None:
    assert mask_coverage((0.5, 0.5), None) == 1.0
    assert mask_coverage((0.5, 0.5), {}) == 0.0
    assert mask_coverage((0.5, 0.5), {"leaves": [], "combine": "union"}) == 0.0


def test_qualifier_rgb_hsl_luma_and_compose() -> None:
    rgb = (0.8, 0.2, 0.1)
    assert qualifier_coverage(rgb, None) == 1.0
    assert (
        qualifier_coverage(
            rgb,
            {"type": "rgb", "channels": [(0.7, 0.5), (0.3, 0.0), (0.2, 0.0)]},
        )
        > 0.0
    )
    assert qualifier_coverage((0.5, 0.5, 0.5), {"type": "hsl", "hue": (0.0, 30.0)}) == 0.0
    assert qualifier_coverage(rgb, {"type": "luma", "inner": 0.3, "outer": 0.05}) > 0.0
    selection = {
        "id": "sel",
        "mask": {
            "combine": "union",
            "leaves": [
                {
                    "type": "radial",
                    "center": (0.5, 0.5),
                    "axes": (0.4, 0.4),
                    "feather": 0.0,
                }
            ],
        },
        "qualifier": {"type": "luma", "inner": 1.0, "outer": 0.0},
        "invert": False,
    }
    inside = evaluate_selection(selection, point=(0.5, 0.5), rgb=(1.0, 1.0, 1.0))
    outside = evaluate_selection(selection, point=(0.0, 0.0), rgb=(1.0, 1.0, 1.0))
    assert inside == pytest.approx(1.0)
    assert outside == pytest.approx(0.0)
    inverted = evaluate_selection(
        {**selection, "invert": True}, point=(0.0, 0.0), rgb=(1.0, 1.0, 1.0)
    )
    assert inverted == pytest.approx(1.0)


def test_spatial_apply_requires_uv_then_blends() -> None:
    grade = {
        "schema_version": 1,
        "evaluator": "managed-sdr-v1",
        "revision": 1,
        "input": {"profile": "bt709-sdr", "technical_lut": None},
        "working": "linear-bt709",
        "steps": [
            {
                "id": "p1",
                "type": "primaries-v1",
                "enabled": True,
                "mix": 1,
                "selection_id": "sel-1",
                "params": {
                    "exposure": 2.0,
                    "kelvin": 6500,
                    "tint": 0,
                    "contrast": 1,
                    "pivot": 0.18,
                    "saturation": 1,
                    "blacks": 0,
                    "shadows": 0,
                    "highlights": 0,
                    "whites": 0,
                },
            }
        ],
        "selections": [
            {
                "id": "sel-1",
                "mask": {
                    "combine": "union",
                    "leaves": [
                        {
                            "type": "linear",
                            "start": (0.5, 0.0),
                            "end": (0.5, 1.0),
                            "feather": 0.0,
                        }
                    ],
                },
                "qualifier": None,
                "invert": False,
            }
        ],
        "animation": [],
        "output": {"profile": "bt709-sdr", "gamut": "clip"},
        "extensions": {},
    }
    sample = (0.4, 0.4, 0.4)
    with pytest.raises(Exception) as exc:
        apply_managed_grade_rgb(sample, grade)
    assert "spatial" in str(exc.value).lower() or getattr(exc.value, "code", "") == "UNSUPPORTED_GRADE"

    left = apply_managed_grade_rgb(sample, grade, uv=(0.25, 0.5))
    right = apply_managed_grade_rgb(sample, grade, uv=(0.75, 0.5))
    # Directed line (0.5,0)→(0.5,1): right side is selected, left is unchanged.
    assert left == pytest.approx(sample, abs=1e-4)
    assert right != pytest.approx(sample, abs=1e-4)


def test_image_apply_preserves_exterior_pixels() -> None:
    grade = {
        "schema_version": 1,
        "evaluator": "managed-sdr-v1",
        "revision": 1,
        "input": {"profile": "bt709-sdr", "technical_lut": None},
        "working": "linear-bt709",
        "steps": [
            {
                "id": "p1",
                "type": "primaries-v1",
                "enabled": True,
                "mix": 1,
                "selection_id": "sel-1",
                "params": {
                    "exposure": 1.0,
                    "kelvin": 6500,
                    "tint": 0,
                    "contrast": 1,
                    "pivot": 0.18,
                    "saturation": 0.0,
                    "blacks": 0,
                    "shadows": 0,
                    "highlights": 0,
                    "whites": 0,
                },
            }
        ],
        "selections": [
            {
                "id": "sel-1",
                "mask": {
                    "combine": "union",
                    "leaves": [
                        {
                            "type": "radial",
                            "center": (0.5, 0.5),
                            "axes": (0.2, 0.2),
                            "feather": 0.0,
                        }
                    ],
                },
                "qualifier": None,
                "invert": False,
            }
        ],
        "animation": [],
        "output": {"profile": "bt709-sdr", "gamut": "clip"},
        "extensions": {},
    }
    pixels = [
        [(0.6, 0.1, 0.1), (0.6, 0.1, 0.1), (0.6, 0.1, 0.1)],
        [(0.6, 0.1, 0.1), (0.6, 0.1, 0.1), (0.6, 0.1, 0.1)],
        [(0.6, 0.1, 0.1), (0.6, 0.1, 0.1), (0.6, 0.1, 0.1)],
    ]
    out = apply_managed_grade_image(pixels, grade)
    # Corner outside radial mask stays chromatic; center desaturates toward gray.
    assert out[0][0] == pytest.approx(pixels[0][0], abs=1e-5)
    assert abs(out[1][1][0] - out[1][1][1]) < abs(pixels[1][1][0] - pixels[1][1][1])


def test_unknown_leaf_fails_closed() -> None:
    with pytest.raises(ManagedSelectionError):
        leaf_coverage((0.5, 0.5), {"type": "magic"})
