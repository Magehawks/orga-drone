"""Inventory pin for permanent creator regression gates (#275/#283/#284).

Fails if required harness modules or living docs disappear. Does not reimplement
feature suites — it keeps the gate system honest and singular.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "tests" / "fixtures" / "regression_gate_modules.json"
MANIFEST = ROOT / "tests" / "fixtures" / "regression_fixture_manifest.json"
COVERAGE = ROOT / "tests" / "fixtures" / "regression_coverage_matrix.json"
MUTATION_SCRIPT = ROOT / "scripts" / "mutation_check_regression_gates.py"

ALLOWED_STATUS = {
    "PASS",
    "PARTIAL",
    "GAP",
    "NOT_RUN",
    "PENDING",
    "PENDING_INTEGRATION",
    "N_A",
    "N/A",
}


def _load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_regression_gate_module_inventory_exists_and_is_complete() -> None:
    payload = _load(MODULES)
    assert payload["schema"] == "orga-drone-regression-gate-modules-v1"
    assert payload["issues"] == [275, 283, 284]
    file_entries = [
        rel
        for key in ("python_modules", "js_modules", "docs")
        for rel in payload[key]
    ]
    # Node ids may include "::"; only the path portion must exist.
    file_entries.extend(
        node.split("::", 1)[0] for node in payload.get("python_gate_nodes", [])
    )
    file_entries.extend(payload.get("js_gate_nodes") or [])
    missing = [rel for rel in sorted(set(file_entries)) if not (ROOT / rel).is_file()]
    assert not missing, f"Required regression gate files missing: {missing}"
    required_mutations = {
        "incorrect_canvas_coordinate_mapping",
        "broken_hsl_export",
        "incorrect_clip_targeting",
        "disabled_persistence",
        "broken_undo_redo",
        "incorrect_transition_timing",
        "broken_loop_mapping",
        "broken_keyframe_interpolation",
        "missing_collage_export_cleanup",
        "incorrect_scope_accumulation",
        "authorization_bypass",
    }
    assert required_mutations <= set(payload["mutation_targets"])
    # Parallel-stream hooks: include when present; never invent missing coverage.
    for rel in payload.get("optional_when_present", []):
        path = ROOT / rel
        if path.is_file():
            continue
        # Absent optional hooks are fine; presence is asserted only when listed as required.


def test_fixture_manifest_is_authoritative() -> None:
    payload = _load(MANIFEST)
    assert payload["schema"] == "orga-drone-regression-fixture-manifest-v1"
    assert 275 in payload["issue_refs"]
    assert 283 in payload["issue_refs"]
    assert 284 in payload["issue_refs"]
    assert any(
        item["id"] == "potensic-representative" for item in payload["optional_real_footage"]
    )
    potensic = next(
        item
        for item in payload["optional_real_footage"]
        if item["id"] == "potensic-representative"
    )
    assert potensic["status"] == "NOT_FABRICATED"
    for item in payload["synthetic"]:
        path = item.get("path")
        if path and item.get("shipped_in_repo"):
            assert (ROOT / path).is_file(), path
    # No competing thin manifest alongside the authoritative file.
    assert not (ROOT / "tests" / "fixtures" / "manifest.json").is_file()


def test_machine_readable_coverage_matrix_is_authoritative() -> None:
    payload = _load(COVERAGE)
    assert payload["schema"] == "orga-drone-regression-coverage-matrix-v1"
    assert payload["issues"] == [275, 283, 284]
    assert payload["develop_sha_at_authoring"]
    assert "Creator regression gates" in payload["ci_required_today"]
    assert "Windows packaged E2E" in payload["ci_main_only"]
    assert payload["po_approval_settings_changes"]
    journeys = payload["journeys"]
    assert len(journeys) >= 12
    ids = {j["id"] for j in journeys}
    for required in (
        "library-import-browse-detail",
        "studio-photo-masks-object-select",
        "color-workspace-operators",
        "color-scopes",
        "video-editing-playback",
        "collage-edit-export",
        "control-api-mcp-assistant",
        "packaged-windows-startup",
        "persistence-undo-redo",
    ):
        assert required in ids
    for journey in journeys:
        for layer, status in journey["layer_status"].items():
            assert status in ALLOWED_STATUS, (journey["id"], layer, status)
        # Browser evidence must never silently claim native PASS.
        if journey["layer_status"].get("4_native_windows_e2e") == "PASS":
            raise AssertionError(
                f"{journey['id']} claims native PASS without dated evidence binding"
            )
        for suite in journey.get("suites", []):
            path = ROOT / suite
            assert path.is_file() or suite.startswith("external:"), suite
    for rel in payload["ui_ux_protection"]["suites"]:
        assert (ROOT / rel).is_file(), rel


def test_single_mutation_harness_exists() -> None:
    assert MUTATION_SCRIPT.is_file()
    text = MUTATION_SCRIPT.read_text(encoding="utf-8")
    for token in (
        "incorrect_canvas_coordinate_mapping",
        "broken_hsl_export",
        "incorrect_clip_targeting",
        "disabled_persistence",
        "broken_undo_redo",
        "incorrect_transition_timing",
        "missing_collage_export_cleanup",
        "incorrect_scope_accumulation",
        "authorization_bypass",
    ):
        assert token in text, token
    # Competing harness name from superseded PR must not return.
    assert not (ROOT / "scripts" / "regression_mutation_check.py").is_file()


@pytest.mark.parametrize(
    ("path", "needle"),
    [
        ("docs/qa/COVERAGE_MATRIX.md", "Wrong-clip targeting"),
        ("docs/qa/COVERAGE_MATRIX.md", "Packaged Windows startup"),
        ("docs/qa/COVERAGE_MATRIX.md", "Close recommendations"),
        ("docs/REGRESSION_GATES.md", "Creator regression gates"),
        ("docs/REGRESSION_GATES.md", "Authoritative artifacts"),
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
