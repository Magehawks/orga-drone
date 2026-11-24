"""Permanent regression gate inventory (#275/#283/#284).

Validates the living coverage matrix and fixture manifest. Does not invent
feature coverage: it fails when referenced suites disappear or when status
vocabulary is abused (for example claiming PASS for NOT_RUN).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "tests/fixtures/regression_coverage_matrix.json"
MANIFEST_PATH = ROOT / "tests/fixtures/regression_fixture_manifest.json"
MUTATION_SCRIPT = ROOT / "scripts/regression_mutation_check.py"

ALLOWED_STATUS = {
    "PASS",
    "PARTIAL",
    "GAP",
    "NOT_RUN",
    "PENDING_INTEGRATION",
    "N_A",
}


@pytest.fixture(scope="module")
def matrix() -> dict:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_matrix_schema_and_issues(matrix: dict) -> None:
    assert matrix["schema"] == "orga-drone-regression-coverage-matrix-v1"
    assert matrix["issues"] == [275, 283, 284]
    assert set(matrix["layers"]) >= {
        "1_unit",
        "2_integration",
        "3_browser_e2e",
        "4_native_windows_e2e",
        "5_visual_performance",
    }
    assert len(matrix["journeys"]) >= 12


def test_status_vocabulary_is_honest(matrix: dict) -> None:
    for journey in matrix["journeys"]:
        for layer, status in journey["layer_status"].items():
            assert status in ALLOWED_STATUS, (journey["id"], layer, status)
        # Native Windows must not be silently labeled PASS without evidence policy.
        native = journey["layer_status"]["4_native_windows_e2e"]
        assert native in {
            "PASS",
            "PARTIAL",
            "GAP",
            "NOT_RUN",
            "PENDING_INTEGRATION",
            "N_A",
        }


def test_referenced_suite_paths_exist(matrix: dict) -> None:
    missing: list[str] = []
    for journey in matrix["journeys"]:
        for rel in journey["suites"]:
            path = ROOT / rel
            if not path.is_file():
                missing.append(f"{journey['id']}: {rel}")
    for rel in matrix["ui_ux_protection"]["suites"]:
        if not (ROOT / rel).is_file():
            missing.append(f"ui_ux: {rel}")
    assert not missing, "Matrix references missing suites:\n" + "\n".join(missing)


def test_fixture_manifest_schema(manifest: dict) -> None:
    assert manifest["schema"] == "orga-drone-regression-fixture-manifest-v1"
    assert 275 in manifest["issue_refs"]
    assert any(item["id"] == "potensic-representative" for item in manifest["optional_real_footage"])
    potensic = next(
        item for item in manifest["optional_real_footage"] if item["id"] == "potensic-representative"
    )
    assert potensic["status"] == "NOT_FABRICATED"
    for item in manifest["synthetic"]:
        path = item.get("path")
        if path and item.get("shipped_in_repo"):
            assert (ROOT / path).is_file(), path


def test_ci_inventory_documents_existing_checks(matrix: dict) -> None:
    required = set(matrix["ci_required_today"])
    assert "Ruff, MyPy and unit tests" in required
    assert "JavaScript lint, format and tests" in required
    assert "App journey smoke" in required
    assert "Windows packaged E2E" in matrix["ci_main_only"]
    assert matrix["po_approval_settings_changes"], "PO approval notes required"


def test_mutation_harness_exists_and_lists_required_cases() -> None:
    assert MUTATION_SCRIPT.is_file()
    text = MUTATION_SCRIPT.read_text(encoding="utf-8")
    for token in (
        "canvas_coordinate_mapping",
        "hsl_export",
        "clip_targeting",
        "persistence",
        "undo_redo",
        "transition_timing",
        "collage_export_cleanup",
        "scope_accumulation",
        "authorization_bypass",
    ):
        assert token in text, token


def test_playwright_is_not_claimed_as_native_windows(matrix: dict) -> None:
    """Browser-layer coverage must never be presented as packaged EXE proof."""
    packaged = next(j for j in matrix["journeys"] if j["id"] == "packaged-windows-startup")
    assert packaged["layer_status"]["3_browser_e2e"] == "N_A"
    assert packaged["layer_status"]["4_native_windows_e2e"] in {
        "NOT_RUN",
        "PASS",
        "PARTIAL",
        "GAP",
        "PENDING_INTEGRATION",
    }
