"""A failed feasibility probe must never leave stale successful evidence."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("existing_exe", [False, True], ids=["missing-exe", "missing-ffmpeg"])
def test_failed_preflight_replaces_old_report(tmp_path: Path, existing_exe: bool) -> None:
    output = tmp_path / "evidence"
    output.mkdir()
    report = output / "report.json"
    report.write_text(
        json.dumps({"status": "EVIDENCE_COLLECTED_NOT_APPROVED", "samples": ["stale"]}),
        encoding="utf-8",
    )
    exe = tmp_path / "missing-app.exe"
    if existing_exe:
        exe.write_bytes(b"synthetic fingerprint fixture, never executed")
    script = Path(__file__).resolve().parents[1] / "packaging/e2e/transition_parity_spike.py"
    result = subprocess.run(
        [sys.executable, str(script), "--exe", str(exe), "--ffmpeg",
         str(tmp_path / "missing-ffmpeg"), "--output-dir", str(output)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1, result.stderr
    evidence = json.loads(report.read_text(encoding="utf-8"))
    assert evidence["status"] == "BLOCKED"
    assert evidence["samples"] == []
    assert evidence["error"].startswith("FileNotFoundError:")
    assert "browser" not in evidence
