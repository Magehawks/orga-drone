"""SFX peak waveforms: trim windows, bad files, and the local cache (#184)."""

from __future__ import annotations

import array
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.ffmpeg_bin import find_ffmpeg
from orga_drone.local_cache import clear_regenerable_cache
from orga_drone.studio_history import clear_studio_history
from orga_drone.studio_sfx_waveform import (
    load_sfx_waveform,
    peaks_from_pcm,
    waveform_cache_dir,
)


def test_peaks_are_quiet_before_the_tone() -> None:
    rate = 8000
    silence = array.array("f", [0.0] * rate)
    tone = array.array("f", [0.4 if index % 2 == 0 else -0.4 for index in range(rate)])
    if sys.byteorder != "little":
        silence.byteswap()
        tone.byteswap()
    peaks = peaks_from_pcm(silence.tobytes() + tone.tobytes(), sample_rate=rate)
    mid = len(peaks) // 2
    assert max(peaks[:mid]) < 0.05
    assert max(peaks[mid:]) > 0.9


def test_missing_and_corrupt_audio_have_no_waveform(tmp_path: Path) -> None:
    missing = load_sfx_waveform(tmp_path / "gone.wav", tmp_path / "cache")
    assert missing.status == "unavailable"
    assert missing.peaks == ()
    corrupt = tmp_path / "broken.wav"
    corrupt.write_bytes(b"not-audio")
    failed = load_sfx_waveform(corrupt, tmp_path / "cache")
    assert failed.status == "unavailable"


def test_ffmpeg_waveform_is_cached_and_clearable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        pytest.skip("ffmpeg not available")
    path = tmp_path / "click.wav"
    generated = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:sample_rate=8000:duration=0.4",
            str(path),
        ],
        check=False,
        capture_output=True,
    )
    assert generated.returncode == 0, generated.stderr
    cache = waveform_cache_dir(tmp_path / "data")
    import orga_drone.studio_sfx_waveform as waveform_module

    calls = {"n": 0}
    real = waveform_module._decode_pcm

    def counting(source: Path) -> tuple[bytes, float] | None:
        calls["n"] += 1
        return real(source)

    monkeypatch.setattr(waveform_module, "_decode_pcm", counting)
    first = load_sfx_waveform(path, cache)
    second = load_sfx_waveform(path, cache)
    assert first.status == "ready"
    assert first.duration_s == pytest.approx(0.4, abs=0.05)
    assert max(first.peaks) > 0.5
    assert second.peaks == first.peaks
    assert calls["n"] == 1
    removed = clear_regenerable_cache(tmp_path / "data")
    assert removed > 0
    assert list(cache.glob("*.json")) == []


def test_waveform_route_for_a_real_file_and_a_broken_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        pytest.skip("ffmpeg not available")
    data = tmp_path / "data"
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=data))
    from orga_drone.app import create_app

    clear_studio_history()
    app = create_app()
    client = TestClient(app)
    db: Database = app.state.db
    project = db.ensure_default_studio_project()
    tone = tmp_path / "wind.wav"
    generated = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=8000:duration=0.3,volume=0",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=8000:duration=0.3",
            "-filter_complex",
            "[0:a][1:a]concat=n=2:v=0:a=1",
            str(tone),
        ],
        check=False,
        capture_output=True,
    )
    assert generated.returncode == 0, generated.stderr
    created = client.post(
        f"/api/studio/projects/{project.id}/sfx",
        json={"path": str(tone.resolve()), "start_s": 1.0},
    )
    assert created.status_code == 200, created.text
    clip = created.json()["clips"][0]
    assert clip["waveform_url"]
    waveform = client.get(clip["waveform_url"])
    assert waveform.status_code == 200
    body = waveform.json()
    assert body["status"] == "ready"
    peaks = body["peaks"]
    mid = len(peaks) // 2
    assert max(peaks[:mid]) < 0.2
    assert max(peaks[mid:]) > 0.8
    tone.write_bytes(b"corrupt")
    broken = client.get(clip["waveform_url"].split("?", 1)[0])
    assert broken.status_code == 200
    assert broken.json()["status"] == "unavailable"
    missing = client.get(f"/api/studio/projects/{project.id}/sfx/99999/waveform")
    assert missing.status_code == 404
