"""Validate the color investigation controls, not a browser color policy."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging/e2e/studio_color_probe.py"


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("studio_color_probe", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("matrix,tag", [("bt709", "bt709"), ("bt601", "smpte170m")])
@pytest.mark.parametrize("color_range", ["tv", "pc"])
def test_fixtures_have_complete_color_tags(
    probe, tmp_path: Path, matrix: str, tag: str, color_range: str
) -> None:
    from orga_drone.ffmpeg_bin import find_ffmpeg

    binary = find_ffmpeg()
    if not binary:
        pytest.skip("FFmpeg is required to validate actual encoded metadata")
    palette = tmp_path / "palette.png"
    Image.new("RGB", (32, 32), (180, 100, 60)).save(palette)
    target = tmp_path / "control.mp4"
    probe.encode_fixture(binary, palette, target, matrix, color_range, "0.1")
    result = subprocess.run(
        [binary, "-hide_banner", "-i", str(target)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    video = next(line for line in result.stderr.splitlines() if "Video:" in line)
    assert f"({color_range}, {tag}," in video
    assert "unknown" not in video


def test_missing_executable_records_incomplete(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--exe",
            str(tmp_path / "missing"),
            "--ffmpeg",
            "missing-ffmpeg",
            "--output-dir",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 1
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "INCOMPLETE"
    assert report["cases"] == []
    assert report["errors"][0].startswith("FileNotFoundError:")


def test_previous_evidence_is_preserved(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text("original", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--exe",
            "missing",
            "--ffmpeg",
            "missing",
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 2
    assert report.read_text(encoding="utf-8") == "original"


def test_changed_sources_cannot_complete_diagnostic(probe) -> None:
    report = {
        "status": "INCOMPLETE",
        "sources_unchanged": False,
        "metadata_only_control_same_yuv": True,
        "cases": [{}] * 7,
        "errors": [],
    }
    with pytest.raises(probe.E2EError, match="Source hashes changed"):
        probe.finish_diagnostic(report)
    assert report["status"] == "INCOMPLETE"
