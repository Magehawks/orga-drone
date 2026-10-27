"""Session Undo/Redo for Studio story edits (Issue #154)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.studio_forward_loop import loop_to_soundtrack_enabled
from orga_drone.studio_history import MAX_STORY_HISTORY, clear_studio_history, history_flags
from orga_drone.studio_image import image_adjust_from_effect_settings


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def _seed(db: Database, root: Path, filename: str, duration_s: float, *, project_id: int | None = None) -> int:
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label=filename)
    media_file = root / filename
    media_file.write_bytes(b"media-bytes-" + filename.encode("ascii"))
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": filename,
            "path": str(media_file.resolve()),
            "size_bytes": media_file.stat().st_size,
            "duration_s": duration_s,
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
        project_id=project_id,
    )
    return clip_id


def _ids(db: Database, project_id: int | None = None) -> list[int]:
    return [item.id for item in db.list_studio_items(project_id)]


def _exposure(db: Database, clip_id: int) -> int:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT project_id FROM studio_clips WHERE id = ?",
            (clip_id,),
        ).fetchone()
    assert row is not None
    stored = {item.id: item for item in db.list_studio_items(int(row["project_id"]))}[clip_id]
    return image_adjust_from_effect_settings(stored.effect_settings).exposure


def test_buttons_start_disabled_and_labels_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    _seed(db, tmp_path / "videos", "A.MP4", 12.0)
    page = client.get("/studio", cookies={"lang": "en"})
    assert page.status_code == 200
    undo = re.search(r'<button[^>]*id="studio-undo"[^>]*>', page.text)
    redo = re.search(r'<button[^>]*id="studio-redo"[^>]*>', page.text)
    assert undo is not None and "disabled" in undo.group(0)
    assert redo is not None and "disabled" in redo.group(0)
    assert 'aria-label="Undo"' in page.text
    assert 'aria-label="Redo"' in page.text
    assert "lucide-undo-2" in page.text
    assert "lucide-redo-2" in page.text
    german = client.get("/studio", cookies={"lang": "de"})
    assert 'aria-label="Rückgängig"' in german.text
    assert 'aria-label="Wiederholen"' in german.text
    script = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    assert "function syncHistoryButtons" in script
    assert "X-Studio-Can-Undo" in script
    assert "function isTextEditingTarget" in script
    assert 'tag === "TEXTAREA"' in script
    assert 'tag === "SELECT"' in script
    assert "isContentEditable" in script
    assert 'type !== "range"' in script
    assert 'if (isTextEditingTarget(document.activeElement)) return;' in script
    assert "event.ctrlKey" in script
    assert 'applyStudioHistory("undo")' in script
    assert 'applyStudioHistory("redo")' in script


def test_cut_remove_trim_reorder_and_redo_invalidation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    first = _seed(db, tmp_path / "a", "A.MP4", 15.0)
    second = _seed(db, tmp_path / "b", "B.MP4", 8.0)
    source = tmp_path / "a" / "A.MP4"
    before = source.read_bytes()
    with db.connect() as conn:
        media_rows = conn.execute("SELECT COUNT(*) AS n FROM media").fetchone()
        assert media_rows is not None
        media_before = int(media_rows["n"])

    moved = client.post("/api/studio/reorder", json={"ordered_ids": [second, first]})
    assert moved.status_code == 200
    assert _ids(db) == [second, first]

    trimmed = client.patch(
        f"/api/studio/{first}/section",
        json={"source_in_s": 1.0, "source_out_s": 6.0, "repeats": 2},
    )
    assert trimmed.status_code == 200
    stored = {item.id: item for item in db.list_studio_items()}[first]
    assert stored.source_start == pytest.approx(1.0)
    assert stored.source_end == pytest.approx(6.0)

    cut = client.post(f"/api/studio/{first}/cut", json={"local_s": 2.0})
    assert cut.status_code == 200
    assert len(_ids(db)) == 3
    removed = client.post(f"/studio/{second}/remove", follow_redirects=False)
    assert removed.status_code == 303
    assert second not in _ids(db)

    undo_remove = client.post("/api/studio/history/undo")
    assert undo_remove.status_code == 200
    assert second in _ids(db)
    undo_cut = client.post("/api/studio/history/undo")
    assert undo_cut.status_code == 200
    assert _ids(db) == [second, first]
    restored = {item.id: item for item in db.list_studio_items()}[first]
    assert restored.source_start == pytest.approx(1.0)
    assert restored.source_end == pytest.approx(6.0)

    redo_cut = client.post("/api/studio/history/redo")
    assert redo_cut.status_code == 200
    assert len(_ids(db)) == 3
    cut_end = {item.id: item for item in db.list_studio_items()}[first].source_end
    fresh = client.patch(
        f"/api/studio/{first}/section",
        json={"source_in_s": 0.0, "source_out_s": 4.0, "repeats": 1},
    )
    assert fresh.status_code == 200
    blocked = client.post("/api/studio/history/redo")
    assert blocked.status_code == 409
    assert {item.id: item for item in db.list_studio_items()}[first].source_end == pytest.approx(4.0)

    undo_trim = client.post("/api/studio/history/undo")
    assert undo_trim.status_code == 200
    assert len(_ids(db)) == 3
    assert {item.id: item for item in db.list_studio_items()}[first].source_end == pytest.approx(
        cut_end
    )
    assert source.read_bytes() == before
    with db.connect() as conn:
        media_rows = conn.execute("SELECT COUNT(*) AS n FROM media").fetchone()
        assert media_rows is not None
        assert int(media_rows["n"]) == media_before


def test_effects_group_into_one_step_and_restart_drops_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed(db, tmp_path / "videos", "C.MP4", 12.0)
    opened = db.resolve_studio_page_project()
    assert opened is not None
    other = db.create_studio_project("Other")
    other_clip = _seed(db, tmp_path / "other", "D.MP4", 9.0, project_id=other.id)
    group = {"X-Studio-History-Group": "brightness"}
    first = client.patch(
        f"/api/studio/{clip_id}/image",
        json={"exposure": 10, "contrast": 0, "saturation": 0, "warmth": 0},
        headers=group,
    )
    second = client.patch(
        f"/api/studio/{clip_id}/image",
        json={"exposure": 35, "contrast": 0, "saturation": 0, "warmth": 0},
        headers=group,
    )
    assert first.status_code == 200
    assert first.headers["x-studio-can-undo"] == "1"
    assert first.headers["x-studio-can-redo"] == "0"
    assert second.status_code == 200
    assert _exposure(db, clip_id) == 35
    undo = client.post("/api/studio/history/undo")
    assert undo.status_code == 200
    assert _exposure(db, clip_id) == 0
    redo = client.post("/api/studio/history/redo")
    assert redo.status_code == 200
    assert _exposure(db, clip_id) == 35

    speed = client.post(f"/api/studio/{clip_id}/speed", json={"speed": 0.5})
    assert speed.status_code == 200
    transition = client.patch(
        f"/api/studio/{clip_id}/transition",
        json={"type": "crossfade", "duration_s": 0.4},
    )
    assert transition.status_code == 200
    ramp = client.patch(
        f"/api/studio/{clip_id}/saturation-ramp",
        json={
            "saturation_ramp": {
                "enabled": True,
                "start_s": 0.2,
                "end_s": 1.5,
                "start_saturation": 100,
                "end_saturation": 0,
            }
        },
    )
    assert ramp.status_code == 200
    masks = client.patch(
        f"/api/studio/{clip_id}/masks",
        json={"masks": [{"effect": "blur", "strength": 40, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}]},
    )
    assert masks.status_code == 200
    frame = client.patch(f"/api/studio/{clip_id}/frame", json={"zoom_start": 1.4})
    assert frame.status_code == 200
    overlays = client.patch(
        f"/api/studio/{clip_id}/overlays",
        json={
            "overlays": [
                {
                    "id": "ovtext0001",
                    "kind": "text",
                    "start_s": 0.2,
                    "end_s": 1.0,
                    "x": 0.1,
                    "y": 0.2,
                    "w": 0.4,
                    "h": 0.16,
                    "rotation": 0,
                    "text": "Ridge",
                    "font_size": 0.06,
                    "color": "#ffffff",
                    "fill": "#00000000",
                    "stroke": "#ffffff",
                    "stroke_width": 0.012,
                    "asset_name": "",
                }
            ]
        },
    )
    assert overlays.status_code == 200
    loop = client.patch(
        f"/api/studio/{clip_id}/loop-effect",
        json={"transition": "cinematic", "duration_s": 1.0, "curve": "smooth"},
    )
    assert loop.status_code == 200
    card = client.post("/api/studio/title-cards")
    assert card.status_code == 200
    card_id = int(card.json()["id"])
    renamed = client.patch(
        f"/api/studio/{card_id}/title-card",
        json={"title": "Hello ridge", "duration_s": 4},
    )
    assert renamed.status_code == 200

    for _ in range(8):
        step = client.post("/api/studio/history/undo")
        assert step.status_code == 200
    assert _exposure(db, clip_id) == 35
    titles = {item.id: item.title_text for item in db.list_studio_items()}
    assert titles.get(card_id) != "Hello ridge"
    stored = {item.id: item for item in db.list_studio_items()}[clip_id]
    assert stored.playback_speed == pytest.approx(1.0)
    assert "blur" not in stored.effect_settings
    assert loop_to_soundtrack_enabled(stored.effect_settings) is False

    missed = client.post(f"/api/studio/{clip_id}/cut", json={"local_s": 0.0})
    assert missed.status_code == 400
    assert history_flags(db.resolve_studio_page_project().id)["can_redo"] is True

    titled = client.patch(
        f"/api/studio/projects/{db.resolve_studio_page_project().id}",
        json={"title": "Renamed story"},
    )
    assert titled.status_code == 200
    assert history_flags(db.resolve_studio_page_project().id)["can_redo"] is True

    mapped = client.patch(
        f"/api/studio/{clip_id}/map",
        json={"enabled": True, "x": 0.2, "y": 0.3, "w": 0.3, "h": 0.24},
    )
    assert mapped.status_code == 200
    assert "map" in {item.id: item for item in db.list_studio_items()}[clip_id].effect_settings

    other_before = [item.effect_settings for item in db.list_studio_items(other.id)]
    clear_studio_history()
    flags = history_flags(db.resolve_studio_page_project().id)
    assert flags == {"can_undo": False, "can_redo": False}
    page = client.get("/studio", cookies={"lang": "en"})
    undo = re.search(r'<button[^>]*id="studio-undo"[^>]*>', page.text)
    assert undo is not None and "disabled" in undo.group(0)
    assert _exposure(db, clip_id) == 35
    assert [item.effect_settings for item in db.list_studio_items(other.id)] == other_before
    assert other_clip in _ids(db, other.id)


def test_history_is_bounded_and_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed(db, tmp_path / "videos", "E.MP4", 10.0)
    opened = db.resolve_studio_page_project()
    assert opened is not None
    other = db.create_studio_project("Side")
    side = _seed(db, tmp_path / "side", "F.MP4", 6.0, project_id=other.id)
    client.patch(
        f"/api/studio/{side}/image",
        json={"exposure": 20, "contrast": 0, "saturation": 0, "warmth": 0},
    )
    for step in range(1, MAX_STORY_HISTORY + 2):
        saved = client.patch(
            f"/api/studio/{clip_id}/image",
            json={"exposure": step, "contrast": 0, "saturation": 0, "warmth": 0},
        )
        assert saved.status_code == 200
    for _ in range(MAX_STORY_HISTORY):
        assert client.post("/api/studio/history/undo").status_code == 200
    assert client.post("/api/studio/history/undo").status_code == 409
    assert _exposure(db, clip_id) == 1
    assert _exposure(db, side) == 20


def test_forward_loop_undo_clears_the_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed(db, tmp_path / "videos", "G.MP4", 20.0)
    project = db.resolve_studio_page_project()
    assert project is not None
    music = tmp_path / "music"
    music.mkdir()
    song = music / "bed.mp3"
    song.write_bytes(b"ID3fake")

    def probe(_file_path: str) -> float | None:
        return 12.0

    original = db._probe_music_duration_s
    db._probe_music_duration_s = probe  # type: ignore[method-assign]
    try:
        db.append_studio_music(project.id, str(song.resolve()))
    finally:
        db._probe_music_duration_s = original  # type: ignore[method-assign]
    saved = client.patch(f"/api/studio/{clip_id}/forward-loop", json={"enabled": True})
    assert saved.status_code == 200
    stored = {item.id: item for item in db.list_studio_items()}[clip_id]
    assert loop_to_soundtrack_enabled(stored.effect_settings) is True
    undo = client.post("/api/studio/history/undo")
    assert undo.status_code == 200
    restored = {item.id: item for item in db.list_studio_items()}[clip_id]
    assert loop_to_soundtrack_enabled(restored.effect_settings) is False
    assert song.read_bytes() == b"ID3fake"
