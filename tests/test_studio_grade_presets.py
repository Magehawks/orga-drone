"""Creative Quick Look → managed primaries compile (#361)."""

from __future__ import annotations

import pytest

from orga_drone.studio_grade_commands import validate_patch
from orga_drone.studio_grade_contract import GradeError
from orga_drone.studio_grade_model import read_grade
from orga_drone.studio_grade_presets import (
    compile_quick_look_to_primaries,
    image_adjust_to_primaries_params,
)
from orga_drone.studio_looks import look_image_adjust


def managed() -> dict:
    return {
        "grade": {
            "schema_version": 1,
            "evaluator": "managed-sdr-v1",
            "revision": 7,
            "input": {"profile": "srgb", "technical_lut": None},
            "working": "linear-bt709",
            "steps": [],
            "selections": [],
            "animation": [],
            "output": {"profile": "bt709-sdr", "gamut": "clip"},
            "extensions": {},
        }
    }


def test_quick_look_compiles_to_inspectable_primaries() -> None:
    compiled = compile_quick_look_to_primaries("cinematic")
    assert compiled["preset_id"] == "cinematic"
    assert compiled["type"] == "primaries-v1"
    assert compiled["source"] == "quick-look-v1"
    image = look_image_adjust("cinematic")
    assert compiled["params"] == image_adjust_to_primaries_params(image)
    assert compiled["params"]["exposure"] == pytest.approx(image.exposure / 100.0)
    assert compiled["params"]["contrast"] == pytest.approx(1.0 + image.contrast / 200.0)


def test_apply_preset_command_writes_primaries_and_extension() -> None:
    model = read_grade(managed())
    result = validate_patch(
        model,
        {
            "type": "apply_preset",
            "project_id": 1,
            "clip_id": 2,
            "expected_revision": 7,
            "params": {"preset_id": "vibrant"},
        },
        7,
    )
    assert result.changed
    step = result.proposed.grade["steps"][0]
    assert step["type"] == "primaries-v1"
    assert step["enabled"] is True
    assert result.proposed.grade["extensions"]["creative_preset"]["id"] == "vibrant"
    # Pro can inspect the same step params without a shadow grade.
    assert "exposure" in step["params"]


def test_apply_preset_rejects_unknown_ids() -> None:
    model = read_grade(managed())
    with pytest.raises(GradeError):
        validate_patch(
            model,
            {
                "type": "apply_preset",
                "project_id": 1,
                "clip_id": 2,
                "expected_revision": 7,
                "params": {"preset_id": "noir"},
            },
            7,
        )
