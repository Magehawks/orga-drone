"""Selection overlay raster preview (#537) — coverage incl. invert/feather."""

from __future__ import annotations

from orga_drone.studio_managed_selection import rasterize_selection_coverage


def test_rasterize_selection_coverage_invert_polygon() -> None:
    selection = {
        "id": "s1",
        "invert": False,
        "mask": {
            "combine": "union",
            "leaves": [
                {
                    "type": "polygon",
                    "points": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]],
                    "feather": 0.0,
                    "closed": True,
                }
            ],
        },
        "qualifier": {"type": "none"},
    }
    width = height = 32
    normal = rasterize_selection_coverage(selection, width=width, height=height)
    inverted = rasterize_selection_coverage(
        {**selection, "invert": True}, width=width, height=height
    )
    assert len(normal) == width * height
    # Center inside polygon should be selected; after invert, near zero.
    center = (height // 2) * width + (width // 2)
    assert normal[center] > 0.9
    assert inverted[center] < 0.1
    # Corner outside polygon: opposite after invert.
    assert normal[0] < 0.1
    assert inverted[0] > 0.9


def test_rasterize_selection_coverage_feather_soft_edge() -> None:
    hard = {
        "invert": False,
        "mask": {
            "combine": "union",
            "leaves": [
                {
                    "type": "polygon",
                    "points": [[0.3, 0.3], [0.7, 0.3], [0.7, 0.7], [0.3, 0.7]],
                    "feather": 0.0,
                    "closed": True,
                }
            ],
        },
        "qualifier": {"type": "none"},
    }
    soft = {
        **hard,
        "mask": {
            "combine": "union",
            "leaves": [
                {
                    **hard["mask"]["leaves"][0],
                    "feather": 0.15,
                }
            ],
        },
    }
    width = height = 48
    hard_w = rasterize_selection_coverage(hard, width=width, height=height)
    soft_w = rasterize_selection_coverage(soft, width=width, height=height)
    # Edge sample near the polygon border should differ with feather.
    edge = int(0.3 * height) * width + int(0.3 * width)
    assert abs(hard_w[edge] - soft_w[edge]) > 0.01 or soft_w[edge] not in (0.0, 1.0)
