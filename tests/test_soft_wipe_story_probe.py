"""Regression tests for the nonshipping #301 measurement harness."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging/e2e/soft_wipe_story_probe.py"


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("soft_wipe_story_probe", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_edge_error_cannot_hide_in_full_frame_average(probe) -> None:
    reference = Image.new("RGB", (640, 360))
    preview = reference.copy()
    ImageDraw.Draw(preview).rectangle((0, 0, 3, 359), fill=(20, 20, 20))
    result = probe.metrics(preview, reference)
    assert result["full"]["mean_rgb"] < 3
    assert result["full"]["p95_max_channel_error"] == 0
    assert result["left_edge"]["p95_max_channel_error"] == 20
    assert not probe.regions_pass(result)


def test_identical_frames_pass_spatial_check(probe) -> None:
    picture = Image.new("RGB", (640, 360), (70, 100, 160))
    assert probe.regions_pass(probe.metrics(picture, picture))


def test_preflight_failure_records_no_go(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--exe", str(tmp_path / "absent.exe"),
         "--ffmpeg", str(tmp_path / "absent-ffmpeg"), "--output-dir", str(output)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 1, result.stderr
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["decision"] == "NO-GO"
    assert report["phase"] == "setup"
    assert report["samples"] == []
    assert report["errors"][0].startswith("FileNotFoundError:")


def test_existing_evidence_is_not_overwritten(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text("original evidence", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--exe", "absent.exe", "--ffmpeg", "absent",
         "--output-dir", str(tmp_path)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 2
    assert report.read_text(encoding="utf-8") == "original evidence"
