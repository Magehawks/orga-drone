"""Forward-loop playback proxy eligibility (issue #294 Phase A).

The JS preview cannot map a color proxy onto forward-loop wraps/overlaps
and manual section repeats yet, so the backend must not generate or
advertise a proxy for those clips. Phase A aligns backend eligibility with
the JS guard and adds truthful loop-cause chip messages.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def _run(*args: str) -> None:
    subprocess.run(
        [find_ffmpeg() or "ffmpeg", "-y", "-loglevel", "error", *args],
        check=True,
        capture_output=True,
        timeout=120,
        **subprocess_no_window_kwargs(),
    )


def _seed_video(db: Database, root: Path, filename: str) -> int:
    """Seed one real 3-second synthetic video clip (skip without ffmpeg)."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg unavailable")
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label=filename)
    media_file = root / filename
    _run(
        "-f", "lavfi", "-i", "color=c=black:s=320x180:r=30:d=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(media_file),
    )
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": filename,
            "path": str(media_file.resolve()),
            "size_bytes": media_file.stat().st_size,
            "duration_s": 3.0,
            "recorded_at": "2024-06-01T12:00:00",
            "sequence": 1,
            "mode": None,
            "drone_model": "Avata 2",
            "camera_model": None,
            "latitude": None,
            "longitude": None,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )
    item = db.get_media(media_id)
    assert item is not None
    clip_id, _created = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
    )
    return clip_id


def _seed_soundtrack(db: Database, tmp_path: Path) -> None:
    """Forward loop needs a project soundtrack with a known duration."""
    project = db.resolve_studio_page_project()
    assert project is not None
    music = tmp_path / "music"
    music.mkdir(exist_ok=True)
    song = music / "bed.mp3"
    song.write_bytes(b"ID3fake")
    original = db._probe_music_duration_s
    db._probe_music_duration_s = lambda _path: 30.0  # type: ignore[method-assign,assignment]
    try:
        db.append_studio_music(project.id, str(song.resolve()))
    finally:
        db._probe_music_duration_s = original  # type: ignore[method-assign]


def _apply_lut(client: TestClient, tmp_path: Path, clip_id: int) -> None:
    cube = tmp_path / "boost.cube"
    lines = ['TITLE "Boost"', "LUT_3D_SIZE 2"] + ["0.2 0.5 0.8"] * 7 + ["1 1 1"]
    cube.write_text("\n".join(lines) + "\n", encoding="utf-8")
    imported = client.post("/api/studio/luts", json={"path": str(cube)})
    assert imported.status_code == 200
    asset = imported.json()["asset_name"]
    colored = client.patch(
        f"/api/studio/{clip_id}/color",
        json={"input_profile": "rec709", "creative_lut": asset, "creative_strength": 80},
    )
    assert colored.status_code == 200


def test_forward_loop_clip_never_builds_or_advertises_a_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A forward-loop clip with a LUT is proxy-ineligible: build is rejected,
    nothing is advertised, and no unusable proxy file is generated."""
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed_video(db, tmp_path / "videos", "LOOP.MP4")
    _apply_lut(client, tmp_path, clip_id)
    _seed_soundtrack(db, tmp_path)
    url = f"/api/studio/{clip_id}/playback-proxy"

    # Sanity: the same clip without loop IS eligible and gets a proxy.
    assert client.post(url).status_code == 200
    page = client.get("/studio")
    assert f'data-lut-proxy-url="{url}"' in page.text
    proxies_before = list((tmp_path / "data" / "playback-proxies").glob("*.mp4"))

    # Enable the forward loop: eligibility must disappear.
    looped = client.patch(f"/api/studio/{clip_id}/forward-loop", json={"enabled": True})
    assert looped.status_code == 200
    # Manual rebuild is refused; the stale built proxy is not advertised.
    assert client.post(url).status_code == 409
    assert f'data-lut-proxy-url="{url}"' not in client.get("/studio").text
    # No NEW unusable proxy file was generated for the loop clip.
    assert list((tmp_path / "data" / "playback-proxies").glob("*.mp4")) == proxies_before

    # Disabling the loop restores eligibility on the next page render.
    unlooped = client.patch(f"/api/studio/{clip_id}/forward-loop", json={"enabled": False})
    assert unlooped.status_code == 200
    assert f'data-lut-proxy-url="{url}"' in client.get("/studio").text


def test_manual_section_repeats_stay_proxy_ineligible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """repeats > 1 was already backend-guarded; lock it with the loop story."""
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed_video(db, tmp_path / "videos", "REPEAT.MP4")
    _apply_lut(client, tmp_path, clip_id)
    url = f"/api/studio/{clip_id}/playback-proxy"
    repeated = client.patch(
        f"/api/studio/{clip_id}/section",
        json={"source_in_s": 0.0, "source_out_s": 2.0, "repeats": 3},
    )
    assert repeated.status_code == 200
    assert client.post(url).status_code == 409
    assert f'data-lut-proxy-url="{url}"' not in client.get("/studio").text


def test_loop_cause_chip_messages_ship_in_de_and_en(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The truthful loop-cause messages exist as data-* contract entries and
    German translations; studio.js selects them for looped playback."""
    client, db = _client(tmp_path, monkeypatch)
    _seed_video(db, tmp_path / "videos", "CHIPS.MP4")  # opens the editor page
    english = client.get("/studio", cookies={"lang": "en"})
    german = client.get("/studio", cookies={"lang": "de"})
    assert english.status_code == 200 and german.status_code == 200
    assert 'data-lut-chip-loop-playing="Playing looped; color file preview appears on pause"' in english.text
    assert 'data-hsl-chip-loop-playing="Playing looped; HSL preview appears on pause"' in english.text
    assert 'data-color-wheels-chip-loop-playing="Playing looped; color grading preview appears on pause"' in english.text
    assert "Loop-Wiedergabe; Farbdatei-Vorschau erscheint bei Pause" in german.text
    assert "Loop-Wiedergabe; HSL-Vorschau erscheint bei Pause" in german.text
    assert "Loop-Wiedergabe; Farbkorrektur-Vorschau erscheint bei Pause" in german.text

    script = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    assert "msgLutChipLoopPlaying" in script
    assert "msgHslChipLoopPlaying" in script
    assert "msgColorWheelsChipLoopPlaying" in script
    # The loop-aware branch checks both loop causes.
    assert "forwardLoopActive(clip) || sectionRepeats(clip) > 1" in script


def test_forward_loop_flag_reads_from_effect_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard mirrors the JS dataset flag: loop_to_soundtrack_enabled
    drives data-forward-loop-active and backend eligibility alike."""
    from orga_drone.studio_forward_loop import loop_to_soundtrack_enabled

    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed_video(db, tmp_path / "videos", "FLAG.MP4")
    _seed_soundtrack(db, tmp_path)
    assert loop_to_soundtrack_enabled(None) is False
    saved = client.patch(f"/api/studio/{clip_id}/forward-loop", json={"enabled": True})
    assert saved.status_code == 200
    stored = {item.id: item for item in db.list_studio_items()}[clip_id]
    assert loop_to_soundtrack_enabled(stored.effect_settings) is True
