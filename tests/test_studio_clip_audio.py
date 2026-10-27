"""An audio-bar trim changes the sound range and leaves the picture alone."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.studio_audio import (
    detached_audio_af,
    detached_audio_from_effect_settings,
    export_audio_args,
)
from orga_drone.studio_export import _clip_to_export_clip
from orga_drone.studio_image import saturation_ramp_from_effect_settings


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def _seed(db: Database, root: Path) -> tuple[int, Path]:
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label="clip")
    media_file = root / "CLIP.MP4"
    media_file.write_bytes(b"clip-bytes-stay")
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": media_file.name,
            "path": str(media_file.resolve()),
            "size_bytes": media_file.stat().st_size,
            "duration_s": 12.0,
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
    return clip_id, media_file


def _stored(db: Database, clip_id: int):
    return next(item for item in db.list_studio_items() if item.id == clip_id)


def test_audio_trim_keeps_video_range_and_export_uses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id, media_file = _seed(db, tmp_path / "videos")
    original = media_file.read_bytes()
    db.set_studio_section(clip_id, source_in_s=1.0, source_out_s=9.0, repeats=1)
    db.set_studio_saturation_ramp(
        clip_id,
        {
            "enabled": True,
            "start_s": 0.0,
            "end_s": 4.0,
            "start_saturation": 100,
            "end_saturation": 0,
        },
    )
    res = client.patch(
        f"/api/studio/{clip_id}/clip-audio",
        json={"source_in_s": 3.0, "source_out_s": 6.0, "place_s": 2.0},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["source_in_s"] == pytest.approx(1.0)
    assert body["source_out_s"] == pytest.approx(9.0)
    assert body["audio"]["source_in_s"] == pytest.approx(3.0)
    assert body["audio"]["source_out_s"] == pytest.approx(6.0)
    assert body["audio"]["place_s"] == pytest.approx(2.0)
    assert media_file.read_bytes() == original

    stored = _stored(db, clip_id)
    assert stored.source_start == pytest.approx(1.0)
    assert stored.source_end == pytest.approx(9.0)
    ramp = saturation_ramp_from_effect_settings(stored.effect_settings)
    assert ramp.enabled is True
    assert ramp.end_saturation == 0
    audio = detached_audio_from_effect_settings(stored.effect_settings)
    assert audio.is_heard is True
    chain = detached_audio_af(
        video_start_s=1.0,
        video_duration_s=8.0,
        audio_in_s=audio.source_in_s,
        audio_out_s=audio.source_out_s,
        place_s=audio.place_s,
    )
    assert "atrim=start=2.000:end=5.000" in chain
    assert "adelay=2000|2000" in chain
    args = export_audio_args(
        video_start_s=1.0,
        video_duration_s=8.0,
        detached=audio,
        slow=False,
    )
    assert args[0] == "-af"
    assert "atrim=start=2.000:end=5.000" in args[1]
    assert export_audio_args(
        video_start_s=1.0,
        video_duration_s=8.0,
        detached=None,
        slow=False,
    ) == []

    exported = _clip_to_export_clip(db, stored)
    assert exported is not None
    assert exported.source_start_s == pytest.approx(1.0)
    assert exported.source_end_s == pytest.approx(9.0)
    assert exported.detached_audio is not None
    assert exported.detached_audio.source_in_s == pytest.approx(3.0)
    assert exported.detached_audio.source_out_s == pytest.approx(6.0)

    undo = client.post("/api/studio/history/undo")
    assert undo.status_code == 200
    assert undo.json()["ok"] is True
    restored = _stored(db, clip_id)
    assert restored.source_start == pytest.approx(1.0)
    assert restored.source_end == pytest.approx(9.0)
    assert detached_audio_from_effect_settings(restored.effect_settings).active is False
    assert media_file.read_bytes() == original


def test_audio_bar_is_a_control_and_picture_edges_remain() -> None:
    script = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    page = Path("src/orga_drone/templates/studio.html").read_text(encoding="utf-8")
    css = Path("src/orga_drone/static/css/app.css").read_text(encoding="utf-8")
    bars = script.split("function makeAudioBar", 1)[1].split("function layoutClipAudio", 1)[0]
    assert "studio-clip-audio-edge-in" in bars
    assert "studio-clip-audio-edge-out" in bars
    assert "pointerdown" in bars
    layout = script.split("function layoutClipAudio", 1)[1].split("function onAudioPointerDown", 1)[0]
    assert "makeAudioBar" in layout
    drag = script.split("function onAudioPointerDown", 1)[1].split("async function saveClipAudio", 1)[0]
    assert 'addEventListener("pointermove"' in drag
    assert 'mode === "move"' in drag
    assert 'mode === "start"' in drag
    save = script.split("async function saveClipAudio", 1)[1].split("function onEffectPointerDown", 1)[0]
    assert "/clip-audio" in save
    assert "dataset.clipAudio" in save
    assert "dataset.sourceIn" not in save
    assert "dataset.sourceOut" not in save
    sync = script.split("function syncClipAudio", 1)[1].split("function applyClipPlayback", 1)[0]
    assert "range.custom" in sync
    assert "range.sourceIn" in sync
    assert "video.muted = false" in sync
    host = css.split(".studio-clip-audio {", 1)[1].split("}", 1)[0]
    assert "pointer-events: none" not in host
    assert "position: absolute" not in host
    bar = css.split(".studio-clip-audio-bar {", 1)[1].split("}", 1)[0]
    assert "pointer-events: auto" in bar
    assert 'data-edge="in"' in page
    assert 'data-edge="out"' in page
    assert "function beginEdgeDrag" in script
    assert 'closest("[data-edge]")' in script
