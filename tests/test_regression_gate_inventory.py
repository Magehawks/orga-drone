"""Inventory pin for permanent creator regression gates (#275/#283/#284).

Fails if required harness modules or living docs disappear. Does not reimplement
feature suites — it keeps the gate system honest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "tests" / "fixtures" / "regression_gate_modules.json"
MANIFEST = ROOT / "tests" / "fixtures" / "manifest.json"
COVERAGE = ROOT / "tests" / "fixtures" / "regression_coverage_matrix.json"


def _load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_regression_gate_module_inventory_exists_and_is_complete() -> None:
    payload = _load(MODULES)
    assert payload["schema"] == "orga-drone-regression-gate-modules-v1"
    assert payload["issues"] == [275, 283, 284]
    missing = [
        rel
        for key in ("python_modules", "js_modules", "docs")
        for rel in payload[key]
        if not (ROOT / rel).is_file()
    ]
    assert not missing, f"Required regression gate files missing: {missing}"
    required_mutations = {
        "incorrect_canvas_coordinate_mapping",
        "broken_hsl_export",
        "incorrect_clip_targeting",
        "disabled_persistence",
        "broken_undo_redo",
        "incorrect_transition_timing",
        "missing_collage_export_cleanup",
        "incorrect_scope_accumulation",
        "authorization_bypass",
    }
    assert required_mutations <= set(payload["mutation_targets"])


def test_fixture_manifest_pins_synthetic_policy() -> None:
    payload = _load(MANIFEST)
    assert payload["schema"] == "orga-drone-fixture-manifest-v1"
    assert payload["optional_real_footage"]["fabricate_dji_or_potensic"] is False
    assert payload["optional_real_footage"]["commit_to_repo"] is False
    for entry in payload["in_repo"]:
        path = ROOT / entry["path"]
        assert path.is_file(), entry["path"]


@pytest.mark.parametrize(
    ("path", "needle"),
    [
        ("docs/qa/COVERAGE_MATRIX.md", "Wrong-clip targeting"),
        ("docs/qa/COVERAGE_MATRIX.md", "Packaged Windows startup"),
        ("docs/qa/COVERAGE_MATRIX.md", "Close recommendations"),
        ("docs/REGRESSION_GATES.md", "Creator regression gates"),
    ],
)
def test_coverage_matrix_documents_mandatory_rows(path: str, needle: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    assert needle in text
    gates = (ROOT / "docs" / "REGRESSION_GATES.md").read_text(encoding="utf-8")
    assert "Do not claim **PASS** for **NOT_RUN**" in gates


def test_control_api_wrong_clip_and_security_tests_remain_named() -> None:
    source = (ROOT / "tests" / "test_control_api.py").read_text(encoding="utf-8")
    for name in (
        "test_apply_action_wrong_clip_target_is_rejected",
        "test_two_clip_undo_binds_original_project_clip_and_command",
        "test_original_preview_has_no_editable_target_and_rejects_old_write_and_undo",
        "test_security_lifecycle_and_payloads",
    ):
        assert f"def {name}" in source


def test_collage_export_cleanup_and_hsl_export_assertions_remain() -> None:
    collage = (ROOT / "tests" / "test_studio_collage_export.py").read_text(encoding="utf-8")
    assert "test_story_cleans_up_failed_segment_and_preserves_existing_export" in collage
    assert "collage-export" in collage
    hsl = (ROOT / "tests" / "test_photo_hsl_export_api.py").read_text(encoding="utf-8")
    assert "_mean_chroma" in hsl
    assert "test_api_export_applies_blue_saturation_minus_100_jpg_and_png" in hsl



def test_machine_readable_coverage_matrix_matches_living_docs() -> None:
    payload = _load(COVERAGE)
    assert payload["schema"] == "orga-drone-regression-coverage-matrix-v1"
    assert payload["issues"] == [275, 283, 284]
    assert payload["develop_sha_at_authoring"]
    journeys = payload["journeys"]
    assert len(journeys) >= 10
    ids = {j["id"] for j in journeys}
    for required in (
        "library-import-browse-detail",
        "control-api-mcp-assistant",
        "packaged-windows-startup",
        "persistence-undo-redo",
    ):
        assert required in ids
    for journey in journeys:
        status = journey["layer_status"]
        assert "4_native_windows_e2e" in status
        # Browser evidence must never silently claim native PASS.
        if status.get("4_native_windows_e2e") == "PASS":
            raise AssertionError(
                f"{journey['id']} claims native PASS without dated evidence binding"
            )
        for suite in journey.get("suites", []):
            path = ROOT / suite
            assert path.is_file() or suite.startswith("external:"), suite

