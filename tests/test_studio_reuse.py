"""Add another scene from a Story clip's original file (Issue #156)."""

from __future__ import annotations

from pathlib import Path

import pytest

from orga_drone.db import Database, make_identity_key
from orga_drone.studio_export import _clip_to_export_clip
from orga_drone.studio_history import history_flags
from orga_drone.studio_reuse import ReuseBlocked, stored_source_range
from tests.test_studio_history import _client, _seed


def test_stored_range_clamps_and_rejects_a_short_span() -> None:
    assert stored_source_range(0, 12, 12) == (None, None)
    start, end = stored_source_range(-2, 4, 12)
    assert start == pytest.approx(0.0)
    assert end == pytest.approx(4.0)
    with pytest.raises(ReuseBlocked) as short:
        stored_source_range(1.0, 1.02, 12)
    assert short.value.code == "too_short"
    with pytest.raises(ReuseBlocked) as outside:
        stored_source_range(20, 22, 12)
    assert outside.value.code == "outside"


def test_reuse_inserts_after_the_clip_and_undo_restores_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    first = _seed(db, tmp_path / "a", "A.MP4", 12.0)
    second = _seed(db, tmp_path / "b", "B.MP4", 4.0)
    opened = db.resolve_studio_page_project()
    assert opened is not None
    trimmed = client.patch(
        f"/api/studio/{first}/section",
        json={"source_in_s": 2.0, "source_out_s": 6.0, "repeats": 1},
    )
    assert trimmed.status_code == 200
    with db.connect() as conn:
        conn.execute(
            """UPDATE studio_clips
               SET effect_settings = ?, playback_speed = 0.5, transition = 'crossfade',
                   transition_duration_s = 0.5, position = 5
               WHERE id = ?""",
            ('{"image":{"exposure":40}}', second),
        )
        conn.execute(
            """UPDATE studio_clips
               SET effect_settings = ?, playback_speed = 0.5, transition = 'crossfade',
                   transition_duration_s = 0.5
               WHERE id = ?""",
            ('{"image":{"exposure":40}}', first),
        )
    before = {
        item.id: (
            item.position,
            item.source_start,
            item.source_end,
            item.effect_settings,
            item.playback_speed,
            item.transition,
            item.transition_duration_s,
        )
        for item in db.list_studio_items(opened.id)
    }
    source = tmp_path / "a" / "A.MP4"
    file_bytes = source.read_bytes()
    with db.connect() as conn:
        media_count = int(conn.execute("SELECT COUNT(*) FROM media").fetchone()[0])

    added = client.post(
        f"/api/studio/{first}/reuse-source",
        json={"source_in_s": 6.0, "source_out_s": 11.0},
    )
    assert added.status_code == 200
    body = added.json()
    new_id = int(body["id"])
    assert body["source_in_s"] == pytest.approx(6.0)
    assert body["source_out_s"] == pytest.approx(11.0)
    items = db.list_studio_items(opened.id)
    assert [item.id for item in items] == [first, new_id, second]
    anchor = items[0]
    created = items[1]
    follower = items[2]
    assert anchor.position == before[first][0]
    assert (anchor.source_start, anchor.source_end) == (pytest.approx(2.0), pytest.approx(6.0))
    assert anchor.effect_settings == '{"image":{"exposure":40}}'
    assert anchor.playback_speed == pytest.approx(0.5)
    assert anchor.transition == "crossfade"
    assert anchor.transition_duration_s == pytest.approx(0.5)
    assert created.position == anchor.position + 1
    assert follower.position == anchor.position + 2
    assert created.media_path == anchor.media_path
    assert created.identity_key == anchor.identity_key
    assert created.source_media_id == anchor.source_media_id
    assert created.effect_settings == "{}"
    assert created.playback_speed == pytest.approx(1.0)
    assert created.transition in {None, "cut"}
    assert created.source_start == pytest.approx(6.0)
    assert source.read_bytes() == file_bytes
    with db.connect() as conn:
        assert int(conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]) == media_count

    reopened = Database(db.path)
    again = reopened.list_studio_items(opened.id)
    exported = _clip_to_export_clip(reopened, again[1])
    assert exported is not None
    assert exported.source_start_s == pytest.approx(6.0)
    assert exported.source_end_s == pytest.approx(11.0)
    assert exported.source_path == source.resolve()

    undo = client.post("/api/studio/history/undo")
    assert undo.status_code == 200
    restored = db.list_studio_items(opened.id)
    assert [item.id for item in restored] == [first, second]
    assert restored[0].source_start == pytest.approx(2.0)
    assert restored[0].effect_settings == '{"image":{"exposure":40}}'
    assert restored[1].position == before[second][0]
    redo = client.post("/api/studio/history/redo")
    assert redo.status_code == 200
    redone = db.list_studio_items(opened.id)
    assert [item.id for item in redone] == [first, new_id, second]
    assert redone[1].source_end == pytest.approx(11.0)
    assert source.read_bytes() == file_bytes

    client.patch(
        f"/api/studio/{first}/section",
        json={"source_in_s": 2.0, "source_out_s": 5.0, "repeats": 1},
    )
    blocked = client.post("/api/studio/history/redo")
    assert blocked.status_code == 409


def test_reuse_keeps_order_when_positions_tie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    first = _seed(db, tmp_path / "a", "A.MP4", 12.0)
    second = _seed(db, tmp_path / "b", "B.MP4", 4.0)
    opened = db.resolve_studio_page_project()
    assert opened is not None
    with db.connect() as conn:
        conn.execute("UPDATE studio_clips SET position = 1")
    added = client.post(
        f"/api/studio/{first}/reuse-source",
        json={"source_in_s": 0.0, "source_out_s": 12.0},
    )
    assert added.status_code == 200
    new_id = int(added.json()["id"])
    items = db.list_studio_items(opened.id)
    assert [item.id for item in items] == [first, new_id, second]
    assert items[1].source_start is None
    assert items[1].source_end is None
    overlap = client.post(
        f"/api/studio/{first}/reuse-source",
        json={"source_in_s": 1.0, "source_out_s": 3.0},
    )
    assert overlap.status_code == 200
    assert db.list_studio_items(opened.id)[0].source_start is None


def test_reuse_refuses_without_a_history_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    video = _seed(db, tmp_path / "a", "A.MP4", 12.0)
    opened = db.resolve_studio_page_project()
    assert opened is not None
    root = tmp_path / "photo"
    root.mkdir()
    root_id = db.add_root(root, label="photo")
    photo_file = root / "still.jpg"
    photo_file.write_bytes(b"photo-bytes")
    photo_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": "still.jpg",
            "path": str(photo_file.resolve()),
            "size_bytes": photo_file.stat().st_size,
            "duration_s": None,
            "recorded_at": "2024-06-01T12:00:00",
            "sequence": 1,
            "mode": None,
            "drone_model": None,
            "camera_model": None,
            "latitude": None,
            "longitude": None,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )
    photo = db.get_media(photo_id)
    assert photo is not None
    photo_clip, _created = db.add_studio_item(
        photo.path,
        identity_key=make_identity_key(photo.filename, photo.size_bytes, photo.recorded_at),
        filename=photo.filename,
        recorded_at=photo.recorded_at,
        kind="photo",
        project_id=opened.id,
    )
    card = db.add_studio_title_card(opened.id, title_text="Hello")
    short = client.post(
        f"/api/studio/{video}/reuse-source",
        json={"source_in_s": 1.0, "source_out_s": 1.02},
        cookies={"lang": "en"},
    )
    assert short.status_code == 400
    assert short.json()["detail"] == "That range is too short."
    assert history_flags(opened.id)["can_undo"] is False
    photo_try = client.post(
        f"/api/studio/{photo_clip}/reuse-source",
        json={"source_in_s": 0, "source_out_s": 1},
        cookies={"lang": "en"},
    )
    assert photo_try.status_code == 400
    assert photo_try.json()["detail"] == "Another scene can only be chosen from a video."
    card_try = client.post(
        f"/api/studio/{card.id}/reuse-source",
        json={"source_in_s": 0, "source_out_s": 1},
        cookies={"lang": "en"},
    )
    assert card_try.status_code == 400
    missing = client.post(
        "/api/studio/999999/reuse-source",
        json={"source_in_s": 0, "source_out_s": 1},
    )
    assert missing.status_code == 404
    (tmp_path / "a" / "A.MP4").unlink()
    offline = client.post(
        f"/api/studio/{video}/reuse-source",
        json={"source_in_s": 0, "source_out_s": 4},
        cookies={"lang": "de"},
    )
    assert offline.status_code == 400
    assert offline.json()["detail"] == (
        "Diese Aufnahme ist offline, deshalb kann keine weitere Szene gewählt werden."
    )
    assert [item.id for item in db.list_studio_items(opened.id) if item.id == video]


def test_reuse_refuses_an_unknown_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    video = _seed(db, tmp_path / "a", "A.MP4", 12.0)
    opened = db.resolve_studio_page_project()
    assert opened is not None
    with db.connect() as conn:
        conn.execute("UPDATE media SET duration_s = NULL")
    refused = client.post(
        f"/api/studio/{video}/reuse-source",
        json={"source_in_s": 0, "source_out_s": 4},
        cookies={"lang": "en"},
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == (
        "The length of this recording is unknown, so a range cannot be chosen."
    )
    assert history_flags(opened.id)["can_undo"] is False


def test_reuse_menu_labels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, db = _client(tmp_path, monkeypatch)
    _seed(db, tmp_path / "a", "A.MP4", 8.0)
    page = client.get("/studio", cookies={"lang": "en"})
    assert page.status_code == 200
    assert 'id="studio-clip-menu-reuse"' in page.text
    assert "Use another scene from the original" in page.text
    assert "Add scene" in page.text
    german = client.get("/studio", cookies={"lang": "de"})
    assert "Weitere Szene aus Original verwenden" in german.text
    assert "Szene hinzufügen" in german.text
    script = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    assert "function seekCatalog" in script
    assert "function openReuseDraft" in script
    assert "/reuse-source" in script
    assert "seekVideoLocal" in script
    persist = script.split("async function persistSection", 1)[1].split("async function", 1)[0]
    assert "if (reuseDraft) return;" in persist
    cut = script.split("async function cutSelectedAtPlayhead", 1)[1].split("async function", 1)[0]
    assert "if (reuseDraft) return;" in cut
    remove = script.split("function removeSelectedStoryClip", 1)[1].split("function ", 1)[0]
    assert "if (reuseDraft) return;" in remove
    assert 'document.querySelector(".studio-clear-form")' in script
    undo = script.split('getElementById("studio-undo")?.addEventListener', 1)[1].split(
        "studio-redo", 1
    )[0]
    assert "if (reuseDraft) return;" in undo
    assert "function openOriginalDraft" in script


def test_original_stays_after_its_scenes_are_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    first = _seed(db, tmp_path / "a", "A.MP4", 12.0)
    second = _seed(db, tmp_path / "b", "B.MP4", 4.0)
    opened = db.resolve_studio_page_project()
    assert opened is not None
    media_id = next(item.media_id for item in db.list_studio_items(opened.id) if item.id == first)
    assert media_id is not None
    untouched = client.post(
        f"/api/studio/media/{media_id}/reuse-source",
        json={"source_in_s": 1.0, "source_out_s": 2.0},
    )
    assert untouched.status_code == 404
    assert len(db.list_studio_items(opened.id)) == 2
    full = client.patch(
        f"/api/studio/{first}/section",
        json={"source_in_s": 0.0, "source_out_s": 12.0, "repeats": 1},
    )
    assert full.status_code == 200
    assert db.list_studio_originals(opened.id) == []
    trimmed = client.patch(
        f"/api/studio/{first}/section",
        json={"source_in_s": 2.0, "source_out_s": 6.0, "repeats": 1},
    )
    assert trimmed.status_code == 200
    originals = db.list_studio_originals(opened.id)
    assert [item["media_id"] for item in originals] == [media_id]
    source = tmp_path / "a" / "A.MP4"
    file_bytes = source.read_bytes()
    with db.connect() as conn:
        conn.execute(
            "UPDATE studio_clips SET effect_settings = ? WHERE id = ?",
            ('{"image":{"exposure":40}}', second),
        )
        media_count = int(conn.execute("SELECT COUNT(*) FROM media").fetchone()[0])
    page = client.get("/studio", cookies={"lang": "en"})
    assert page.status_code == 200
    assert 'id="studio-originals"' in page.text
    assert "Full recording" in page.text
    german = client.get("/studio", cookies={"lang": "de"})
    assert "Vollständige Aufnahme" in german.text

    removed = client.post(f"/studio/{first}/remove")
    assert removed.status_code == 200
    assert [item.id for item in db.list_studio_items(opened.id)] == [second]
    assert db.list_studio_originals(opened.id)[0]["media_id"] == media_id

    added = client.post(
        f"/api/studio/media/{media_id}/reuse-source",
        json={"source_in_s": 8.0, "source_out_s": 11.0, "before_id": second},
    )
    assert added.status_code == 200
    new_id = int(added.json()["id"])
    items = db.list_studio_items(opened.id)
    assert [item.id for item in items] == [new_id, second]
    assert items[0].source_start == pytest.approx(8.0)
    assert items[0].source_end == pytest.approx(11.0)
    assert items[0].effect_settings == "{}"
    assert items[0].playback_speed == pytest.approx(1.0)
    assert items[1].effect_settings == '{"image":{"exposure":40}}'
    assert items[1].id == second
    assert source.read_bytes() == file_bytes
    with db.connect() as conn:
        assert int(conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]) == media_count

    undo = client.post("/api/studio/history/undo")
    assert undo.status_code == 200
    assert [item.id for item in db.list_studio_items(opened.id)] == [second]
    assert db.list_studio_originals(opened.id)[0]["media_id"] == media_id
    redo = client.post("/api/studio/history/redo")
    assert redo.status_code == 200
    assert [item.id for item in db.list_studio_items(opened.id)][0] == new_id

    client.post(f"/studio/{new_id}/remove")
    client.post(f"/studio/{second}/remove")
    assert db.list_studio_items(opened.id) == []
    reopened = Database(db.path)
    assert [item["filename"] for item in reopened.list_studio_originals(opened.id)] == ["A.MP4"]
    empty = client.get("/studio", cookies={"lang": "en"})
    assert 'id="studio-preview-video"' in empty.text
    assert 'id="studio-originals"' in empty.text
    assert source.read_bytes() == file_bytes
