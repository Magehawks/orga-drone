"""Validate the LUT smoke's baseline-aware parity gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging/e2e/studio_lut_smoke.py"


@pytest.fixture
def smoke(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("studio_lut_smoke", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bounded_gate_accepts_the_fixed_two_level_cube(smoke) -> None:
    result = smoke.lut_parity_decision(4.0, 4.0, 2.667)
    assert result["strict_parity_pass"] is False
    assert result["parity_pass"] is True
    assert result["tolerance_max_swatch_mean_rgb"] == pytest.approx(4.167)
    assert result["lut_max_extra_over_baseline"] == pytest.approx(1.333)
    assert result["decision"] == "GO_BOUNDED_FIXTURE"


def test_bounded_gate_rejects_the_original_sampling_failure(smoke) -> None:
    result = smoke.lut_parity_decision(36.333, 36.333, 2.667)
    assert result["parity_pass"] is False
    assert result["decision"] == "NO-GO"


def test_strict_gate_still_applies_without_a_color_baseline(smoke) -> None:
    result = smoke.lut_parity_decision(3.1, 3.1, 0.0)
    assert result["strict_parity_pass"] is False
    assert result["parity_pass"] is False


def test_baseline_above_strict_tolerance_lifts_the_bounded_gate(smoke) -> None:
    result = smoke.lut_parity_decision(11.0, 11.0, 10.0)
    assert result["tolerance_max_swatch_mean_rgb"] == pytest.approx(11.5)
    assert result["parity_pass"] is True

def test_seek_measurement_is_part_of_the_bounded_gate(smoke) -> None:
    result = smoke.lut_parity_decision(2.0, 2.0, 2.667, seek_max=5.0)
    assert result["parity_pass"] is False
    assert result["decision"] == "NO-GO"