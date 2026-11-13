"""Shared grade command bridge (#363)."""

from __future__ import annotations

import json

import pytest

from orga_drone.studio_actions import prepare_action, resolve_action_spec
from orga_drone.studio_grade_bridge import (
    apply_grade_command_text,
    grade_capability_report,
    propose_grade_command,
)
from orga_drone.studio_grade_contract import GradeError
from orga_drone.studio_grade_model import read_grade


def _managed_document() -> dict:
    return {
        "grade": {
            "schema_version": 1,
            "evaluator": "managed-sdr-v1",
            "revision": 4,
            "input": {"profile": "srgb", "technical_lut": None},
            "working": "linear-bt709",
            "steps": [
                {
                    "id": "step-1",
                    "type": "primaries-v1",
                    "enabled": True,
                    "mix": 1,
                    "params": {"exposure": 0.5},
                    "selection_id": None,
                }
            ],
            "selections": [],
            "animation": [],
            "output": {"profile": "bt709-sdr", "gamut": "clip"},
            "extensions": {},
        },
        "vendor_keep": {"nested": True},
    }


def test_capability_report_lists_managed_ops_and_commands() -> None:
    model = read_grade(_managed_document())
    report = grade_capability_report(model)
    assert report["writes"] is True
    assert "set_step_enabled" in report["commands"]
    assert "upsert_animation" in report["commands"]
    assert "primaries-v1" in report["operations"]
    assert report["operations"]["primaries-v1"]["animation"]["exposure"]["interpolation"] == "linear"


def test_propose_and_publish_preserves_opaque_root() -> None:
    raw = json.dumps(_managed_document())
    command = {
        "type": "set_step_mix",
        "project_id": 1,
        "clip_id": 2,
        "expected_revision": 4,
        "params": {"step_id": "step-1", "mix": 0.25},
    }
    proposed = propose_grade_command(raw, command, expected_revision=4)
    assert proposed.changed is True
    published = apply_grade_command_text(raw, command, expected_revision=4)
    model = read_grade(published)
    assert model.revision == 5
    assert model.steps[0]["mix"] == 0.25
    assert model.to_dict()["vendor_keep"] == {"nested": True}


def test_stale_revision_rejects() -> None:
    raw = json.dumps(_managed_document())
    command = {
        "type": "set_step_enabled",
        "project_id": 1,
        "clip_id": 2,
        "expected_revision": 99,
        "params": {"step_id": "step-1", "enabled": False},
    }
    with pytest.raises(GradeError) as excinfo:
        propose_grade_command(raw, command, expected_revision=99)
    assert excinfo.value.code == "STALE_REVISION"


def test_control_prepare_action_grade_command() -> None:
    raw = json.dumps(_managed_document())
    spec = resolve_action_spec("clip.grade.command", 1)
    prepared = prepare_action(
        spec,
        raw,
        {
            "type": "set_step_enabled",
            "expected_revision": 4,
            "params": {"step_id": "step-1", "enabled": False},
            "project_id": 9,
            "clip_id": 3,
        },
        set(),
        __import__("pathlib").Path("."),
    )
    model = read_grade(prepared)
    assert model.steps[0]["enabled"] is False
    assert model.revision == 5
