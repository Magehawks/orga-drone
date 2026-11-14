"""Local RC safety/reporting must fail closed without publishing anything."""

import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "packaging/rc" / f"{name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_or_invalid_timing_cannot_be_reported_as_a_pass() -> None:
    smoke = load("smoke_manual_rc")
    assert smoke.timing_gate(None) == "NOT TESTED"
    for invalid in (-1.0, float("nan"), float("inf")):
        assert smoke.timing_gate(invalid) == "FAIL"
    assert smoke.timing_gate(0.1) == "FAIL"


def test_one_frame_rounding_does_not_allow_two_frames() -> None:
    smoke = load("smoke_manual_rc")
    assert smoke.timing_gate(0.0) == "PASS"
    assert smoke.timing_gate(0.033334) == "PASS"
    assert smoke.timing_gate(2 / 30) == "FAIL"


def test_bounded_color_success_does_not_replace_a_strict_failure() -> None:
    smoke = load("smoke_manual_rc")
    observed = {"parity_pass": True, "strict_parity_pass": False}
    assert smoke.gate_result(observed["parity_pass"]) == "PASS"
    assert smoke.gate_result(observed["strict_parity_pass"]) == "FAIL"
    assert smoke.gate_result(observed.get("human_acceptance")) == "NOT TESTED"
    assert smoke.gate_result("PASS") == "FAIL"


def test_packager_refuses_to_replace_an_existing_candidate(
    tmp_path, monkeypatch
) -> None:
    packager = load("package_manual_rc")
    marker = tmp_path / "keep.txt"
    marker.write_text("existing candidate", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "package_manual_rc",
            "--bundle",
            "absent",
            "--analysis-toc",
            "absent",
            "--build-sha",
            "unused",
            "--output-dir",
            str(tmp_path),
        ],
    )
    with pytest.raises(SystemExit) as error:
        packager.main()
    assert error.value.code == 2
    assert marker.read_text(encoding="utf-8") == "existing candidate"
