"""Studio time-canvas foundation (Issue #33 / slice 1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.studio_transition import (
    TYPE_CROSSFADE,
    TYPE_FADE_BLACK,
    AppliedTransition,
    clip_flex_s,
    story_length_s,
)


def _seed_media(
    db: Database,
    root_path: Path,
    *,
    filename: str,
    kind: str,
    duration_s: float | None,
    content: bytes = b"x",
) -> int:
    root_path.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root_path, label="test")
    media_file = root_path / filename
    media_file.write_bytes(content)
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": kind,
            "filename": filename,
            "path": str(media_file.resolve()),
            "size_bytes": len(content),
            "duration_s": duration_s,
            "recorded_at": "2024-01-02T10:00:00",
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


def _add(db: Database, media_id: int) -> int:
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


def _studio_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def test_clip_flex_matches_story_occupancy_not_raw_duration() -> None:
    xf = AppliedTransition(
        type=TYPE_CROSSFADE,
        duration_s=0.5,
        stored_type=TYPE_CROSSFADE,
        stored_duration_s=0.5,
        fallback_cut=False,
        clamped=False,
    )
    fade = AppliedTransition(
        type=TYPE_FADE_BLACK,
        duration_s=0.5,
        stored_type=TYPE_FADE_BLACK,
        stored_duration_s=0.5,
        fallback_cut=False,
        clamped=False,
    )
    assert clip_flex_s(3.0, xf) == pytest.approx(2.5)
    assert clip_flex_s(30.0, fade) == pytest.approx(30.0)
    assert clip_flex_s(12.0, None) == pytest.approx(12.0)
    assert story_length_s([3.0, 30.0], [xf]) == pytest.approx(32.5)
    assert story_length_s([3.0, 30.0], [fade]) == pytest.approx(33.0)


def test_studio_page_has_time_canvas_and_zoom_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _studio_client(tmp_path, monkeypatch)
    photo = _seed_media(
        db, tmp_path / "lib", filename="P.JPG", kind="photo", duration_s=None
    )
    video = _seed_media(
        db, tmp_path / "lib", filename="V.MP4", kind="video", duration_s=30.0
    )
    _add(db, photo)
    _add(db, video)
    html = client.get("/studio").text
    assert 'id="studio-timeline-scroll"' in html
    assert 'id="studio-timeline-canvas"' in html
    assert 'data-timeline-zoom="fit"' in html
    assert 'data-timeline-zoom="in"' in html
    assert 'data-timeline-zoom="out"' in html
    assert "Fit to story" in html or "An Story anpassen" in html
    assert 'id="studio-playhead"' in html
    assert 'role="slider"' in html
    assert "studio-music-track" in html
    assert "studio-track-voice" in html
    assert html.find("studio-timeline-canvas") < html.find("studio-music-track")
    assert 'data-occupancy-s="3.0000"' in html
    assert 'data-occupancy-s="30.0000"' in html
    root = Path(__file__).resolve().parents[1]
    css = (root / "src" / "orga_drone" / "static" / "css" / "app.css").read_text(
        encoding="utf-8"
    )
    assert "flex: var(--clip-flex" not in css
    assert "flex: 0 0 1.35rem" not in css
    js = (root / "src" / "orga_drone" / "static" / "js" / "studio.js").read_text(
        encoding="utf-8"
    )
    assert "function timelinePxPerSecond" in js
    assert "function timeToX" in js
    assert "function xToTime" in js
    assert 'event.key === "ArrowLeft"' in js
    assert 'event.key === "Home"' in js
    assert "TIMELINE_HIT_MIN_PX" in js
    assert "addEventListener(\"wheel\"" not in js
    assert "timeline: {" in js
    assert "projectId" in js
    occupancy_src = js.split("function clipOccupancyS", 1)[1].split(
        "function timelineViewportPx", 1
    )[0]
    assert "index < listLength - 1" in occupancy_src
    assert "crossfade" in occupancy_src
    assert "function nextZoomIndexAbove" in js
    assert "function updateZoomControls" in js
    assert "if (next < 0) return;" in js


def test_crossfade_occupancy_shrinks_html_not_fade_black(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _studio_client(tmp_path, monkeypatch)
    a = _seed_media(db, tmp_path / "lib", filename="A.MP4", kind="video", duration_s=12.0)
    b = _seed_media(db, tmp_path / "lib", filename="B.MP4", kind="video", duration_s=12.0)
    id_a = _add(db, a)
    id_b = _add(db, b)
    db.set_studio_transition(id_a, TYPE_CROSSFADE, 0.5)
    html = client.get("/studio").text
    grid = html.split('id="studio-grid"', 1)[1].split("</ol>", 1)[0]
    block_a = grid.split(f'data-studio-id="{id_a}"', 1)[1].split("data-studio-id=", 1)[0]
    assert 'data-occupancy-s="11.5000"' in block_a
    block_b = grid.split(f'data-studio-id="{id_b}"', 1)[1].split("</li>", 1)[0]
    assert 'data-occupancy-s="12.0000"' in block_b

    db.set_studio_transition(id_a, TYPE_FADE_BLACK, 0.5)
    html_fade = client.get("/studio").text
    grid_fade = html_fade.split('id="studio-grid"', 1)[1].split("</ol>", 1)[0]
    block_fade = grid_fade.split(f'data-studio-id="{id_a}"', 1)[1].split(
        "data-studio-id=", 1
    )[0]
    assert 'data-occupancy-s="12.0000"' in block_fade
    assert "studio-transition" in html_fade
    assert story_length_s([12.0, 12.0], [
        AppliedTransition(
            type=TYPE_FADE_BLACK,
            duration_s=0.5,
            stored_type=TYPE_FADE_BLACK,
            stored_duration_s=0.5,
            fallback_cut=False,
            clamped=False,
        )
    ]) == pytest.approx(24.0)


def test_last_clip_stored_crossfade_does_not_shrink_occupancy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outgoing Crossfade on the last clip is ignored (same as apply_boundaries)."""
    client, db = _studio_client(tmp_path, monkeypatch)
    a = _seed_media(db, tmp_path / "lib", filename="A.MP4", kind="video", duration_s=12.0)
    b = _seed_media(db, tmp_path / "lib", filename="B.MP4", kind="video", duration_s=12.0)
    id_a = _add(db, a)
    id_b = _add(db, b)
    db.set_studio_transition(id_b, TYPE_CROSSFADE, 0.5)
    html = client.get("/studio").text
    grid = html.split('id="studio-grid"', 1)[1].split("</ol>", 1)[0]
    block_a = grid.split(f'data-studio-id="{id_a}"', 1)[1].split("data-studio-id=", 1)[0]
    block_b = grid.split(f'data-studio-id="{id_b}"', 1)[1].split("</li>", 1)[0]
    assert 'data-occupancy-s="12.0000"' in block_a
    assert 'data-occupancy-s="12.0000"' in block_b
    assert story_length_s([12.0, 12.0], []) == pytest.approx(24.0)
