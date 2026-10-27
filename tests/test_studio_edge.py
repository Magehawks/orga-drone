"""Drag the left and right edges of a Story video (Issue #157)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.studio_cut import MIN_SEGMENT_S, edge_source_after_drag
from orga_drone.studio_export import _clip_to_export_clip
from orga_drone.studio_image import image_adjust_from_effect_settings
from orga_drone.studio_transition import TYPE_CROSSFADE


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def _seed(
    db: Database,
    root: Path,
    filename: str,
    *,
    kind: str = "video",
    duration_s: float | None = 12.0,
) -> int:
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label=filename)
    media_file = root / filename
    media_file.write_bytes(b"media-bytes-" + filename.encode("ascii"))
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": kind,
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
    )
    return clip_id


def _clip(db: Database, clip_id: int):
    return {item.id: item for item in db.list_studio_items()}[clip_id]


def _li(html: str, clip_id: int) -> str:
    grid = html.split('id="studio-grid"', 1)[1]
    return grid.split(f'data-studio-id="{clip_id}"', 1)[1].split("</li>", 1)[0]


def test_edge_math_stays_inside_the_file_for_both_edges() -> None:
    right = edge_source_after_drag(
        edge="out",
        source_in_s=0.0,
        source_out_s=10.0,
        delta_story_s=1.5,
        media_duration_s=12.0,
    )
    assert right == pytest.approx((0.0, 11.5))
    stopped = edge_source_after_drag(
        edge="out",
        source_in_s=0.0,
        source_out_s=10.0,
        delta_story_s=9.0,
        media_duration_s=12.0,
    )
    assert stopped == pytest.approx((0.0, 12.0))
    left = edge_source_after_drag(
        edge="in",
        source_in_s=2.0,
        source_out_s=10.0,
        delta_story_s=-3.0,
        media_duration_s=12.0,
    )
    assert left == pytest.approx((0.0, 10.0))
    inward = edge_source_after_drag(
        edge="in",
        source_in_s=2.0,
        source_out_s=10.0,
        delta_story_s=20.0,
        media_duration_s=12.0,
    )
    assert inward[0] == pytest.approx(10.0 - MIN_SEGMENT_S)
    assert inward[1] == pytest.approx(10.0)
    short = edge_source_after_drag(
        edge="out",
        source_in_s=4.0,
        source_out_s=8.0,
        delta_story_s=-20.0,
        media_duration_s=12.0,
    )
    assert short[0] == pytest.approx(4.0)
    assert short[1] == pytest.approx(4.0 + MIN_SEGMENT_S)
    half = edge_source_after_drag(
        edge="out",
        source_in_s=1.0,
        source_out_s=5.0,
        delta_story_s=2.0,
        playback_speed=0.5,
        repeats=1,
        media_duration_s=12.0,
    )
    assert half == pytest.approx((1.0, 6.0))
    repeated = edge_source_after_drag(
        edge="in",
        source_in_s=2.0,
        source_out_s=6.0,
        delta_story_s=4.0,
        playback_speed=1.0,
        repeats=4,
        media_duration_s=12.0,
    )
    assert repeated == pytest.approx((3.0, 6.0))
    with pytest.raises(ValueError):
        edge_source_after_drag(
            edge="slip",
            source_in_s=0.0,
            source_out_s=1.0,
            delta_story_s=0.0,
            media_duration_s=12.0,
        )


def test_trimmed_edges_persist_undo_and_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    video_id = _seed(db, tmp_path / "a", "A.MP4", duration_s=12.0)
    neighbor_id = _seed(db, tmp_path / "b", "B.MP4", duration_s=8.0)
    source = tmp_path / "a" / "A.MP4"
    before = source.read_bytes()
    video_id = db.set_studio_playback_speed(video_id, 0.5)[1]
    db.set_studio_image_adjust(video_id, {"exposure": 25, "warmth": -10})
    db.set_studio_image_adjust(neighbor_id, {"contrast": -20})
    db.set_studio_transition(video_id, TYPE_CROSSFADE, 0.5)
    neighbor_before = _clip(db, neighbor_id)

    first = edge_source_after_drag(
        edge="out",
        source_in_s=0.0,
        source_out_s=12.0,
        delta_story_s=-4.0,
        playback_speed=0.5,
        media_duration_s=12.0,
    )
    assert first == pytest.approx((0.0, 10.0))
    trimmed = client.patch(
        f"/api/studio/{video_id}/section",
        json={"source_in_s": first[0], "source_out_s": first[1], "repeats": 2},
    )
    assert trimmed.status_code == 200
    body = trimmed.json()
    assert body["source_in_s"] == pytest.approx(0.0)
    assert body["source_out_s"] == pytest.approx(10.0)
    assert body["section_repeats"] == 2
    assert body["effective_duration_s"] == pytest.approx(40.0)

    second = edge_source_after_drag(
        edge="in",
        source_in_s=0.0,
        source_out_s=10.0,
        delta_story_s=4.0,
        playback_speed=0.5,
        repeats=2,
        media_duration_s=12.0,
    )
    assert second == pytest.approx((1.0, 10.0))
    opened = client.patch(
        f"/api/studio/{video_id}/section",
        json={"source_in_s": second[0], "source_out_s": second[1], "repeats": 2},
    )
    assert opened.status_code == 200
    assert opened.json()["effective_duration_s"] == pytest.approx(36.0)

    stored = _clip(db, video_id)
    assert stored.source_start == pytest.approx(1.0)
    assert stored.source_end == pytest.approx(10.0)
    assert stored.playback_speed == pytest.approx(0.5)
    assert stored.transition == TYPE_CROSSFADE
    assert image_adjust_from_effect_settings(stored.effect_settings).exposure == 25
    neighbor = _clip(db, neighbor_id)
    assert neighbor.source_start == neighbor_before.source_start
    assert neighbor.source_end == neighbor_before.source_end
    assert image_adjust_from_effect_settings(neighbor.effect_settings).contrast == -20
    assert source.read_bytes() == before

    reopened = Database(db.path)
    again = {item.id: item for item in reopened.list_studio_items()}[video_id]
    assert again.source_start == pytest.approx(1.0)
    assert again.source_end == pytest.approx(10.0)
    exported = _clip_to_export_clip(db, again)
    assert exported is not None
    assert exported.source_start_s == pytest.approx(1.0)
    assert exported.source_end_s == pytest.approx(10.0)
    assert exported.playback_speed == pytest.approx(0.5)
    assert exported.section_repeats == 2
    assert exported.duration_s == pytest.approx(36.0)
    assert exported.source_path == source.resolve()

    undo = client.post("/api/studio/history/undo")
    assert undo.status_code == 200
    restored = _clip(db, video_id)
    assert restored.source_start == pytest.approx(0.0)
    assert restored.source_end == pytest.approx(10.0)
    redo = client.post("/api/studio/history/redo")
    assert redo.status_code == 200
    assert _clip(db, video_id).source_start == pytest.approx(1.0)
    later = client.patch(
        f"/api/studio/{video_id}/section",
        json={"source_in_s": 1.0, "source_out_s": 9.0, "repeats": 2},
    )
    assert later.status_code == 200
    client.post("/api/studio/history/undo")
    assert _clip(db, video_id).source_end == pytest.approx(10.0)
    client.post("/api/studio/history/undo")
    assert _clip(db, video_id).source_start == pytest.approx(0.0)
    assert _clip(db, video_id).source_end == pytest.approx(10.0)

    blocked = client.patch(
        f"/api/studio/{video_id}/section",
        json={"source_in_s": -1.0, "source_out_s": 4.0, "repeats": 1},
    )
    assert blocked.status_code == 400
    full = client.patch(
        f"/api/studio/{video_id}/section",
        json={"source_in_s": 0.0, "source_out_s": 99.0, "repeats": 1},
    )
    assert full.status_code == 200
    assert full.json()["source_in_s"] is None
    assert full.json()["source_out_s"] is None
    assert source.read_bytes() == before


def test_one_history_group_is_one_edge_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed(db, tmp_path / "a", "A.MP4", duration_s=12.0)
    headers = {"X-Studio-History-Group": "edge-1"}
    first = client.patch(
        f"/api/studio/{clip_id}/section",
        json={"source_in_s": 1.0, "source_out_s": 8.0, "repeats": 1},
        headers=headers,
    )
    second = client.patch(
        f"/api/studio/{clip_id}/section",
        json={"source_in_s": 1.0, "source_out_s": 9.0, "repeats": 1},
        headers=headers,
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert _clip(db, clip_id).source_end == pytest.approx(9.0)
    undo = client.post("/api/studio/history/undo")
    assert undo.status_code == 200
    restored = _clip(db, clip_id)
    assert restored.source_start is None
    assert restored.source_end is None


def test_handles_are_video_only_and_labeled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    video_id = _seed(db, tmp_path / "a", "A.MP4", duration_s=12.0)
    photo_id = _seed(db, tmp_path / "p", "P.JPG", kind="photo", duration_s=None)
    unknown_id = _seed(db, tmp_path / "u", "U.MP4", duration_s=None)
    client.patch(
        f"/api/studio/{video_id}/section",
        json={"source_in_s": 1.0, "source_out_s": 4.0, "repeats": 1},
    )
    page = client.get("/studio", cookies={"lang": "en"})
    assert page.status_code == 200
    video = _li(page.text, video_id)
    assert 'data-edge="in"' in video
    assert 'data-edge="out"' in video
    assert 'aria-label="Trim start"' in video
    assert 'aria-label="Trim end"' in video
    assert 'data-source-in="1.0"' in video or 'data-source-in="1"' in video
    photo = _li(page.text, photo_id)
    unknown = _li(page.text, unknown_id)
    assert "data-edge" not in photo
    assert "data-edge" not in unknown
    german = client.get("/studio", cookies={"lang": "de"})
    de_video = _li(german.text, video_id)
    assert 'aria-label="Anfang ziehen"' in de_video
    assert 'aria-label="Ende ziehen"' in de_video

    js = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    css = Path("src/orga_drone/static/css/app.css").read_text(encoding="utf-8")
    move = js.split("function onEdgePointerMove", 1)[1].split("function finishEdgeDrag", 1)[0]
    finish = js.split("function finishEdgeDrag", 1)[1].split("function onEdgePointerUp", 1)[0]
    begin = js.split("function beginEdgeDrag", 1)[1].split("function seekFromClientX", 1)[0]
    assert "persistSection" not in move
    assert "fetch(" not in move
    assert finish.count("persistSection(") == 1
    assert "if (reuseDraft || event.button !== 0) return;" in begin
    assert 'finishEdgeDrag(false)' in js
    assert "function edgeSourceAfterDrag" in js
    assert "cursor: ew-resize" in css
    assert "studio-edge-readout" in js
    assert ".studio-edge-in" in css
    assert ".studio-edge-out" in css
