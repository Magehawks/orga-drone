"""Contract gate: spatial grades stay on CPU materialize (#511)."""

from __future__ import annotations

from orga_drone.studio_managed_apply import (
    grade_needs_cpu_materialize,
    grade_is_managed_pointwise,
)
import json


def _spatial_effect() -> str:
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
                "params": {"exposure": 0.1, "kelvin": 6500, "tint": 0, "contrast": 1.0,
                           "pivot": 0.18, "saturation": 1.0, "blacks": 0, "shadows": 0,
                           "highlights": 0, "whites": 0},
            }
        ],
        "selections": [
            {
                "id": "sel-1",
                "invert": False,
                "mask": {
                    "combine": "union",
                    "leaves": [
                        {
                            "type": "radial",
                            "center": [0.5, 0.5],
                            "axes": [0.2, 0.2],
                            "feather": 0.05,
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
    return json.dumps({"grade": grade})


def test_spatial_grade_requires_cpu_materialize_not_pointwise_webgl() -> None:
    raw = _spatial_effect()
    assert grade_needs_cpu_materialize(raw) is True
    assert grade_is_managed_pointwise(raw) is False
