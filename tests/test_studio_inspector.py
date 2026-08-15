"""Studio selection grammar and Inspector clarity (Issue #34 / slice 2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key


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


def test_studio_inspector_selection_markup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    video = _seed_media(
        db, tmp_path / "lib", filename="V.MP4", kind="video", duration_s=12.0
    )
    photo = _seed_media(
        db, tmp_path / "lib", filename="P.JPG", kind="photo", duration_s=None
    )
    _add(db, video)
    _add(db, photo)
    html = TestClient(app).get("/studio").text
    assert 'id="studio-inspector-heading"' in html
    assert 'id="inspector-empty-title"' in html
    assert 'id="inspector-video-timing"' in html
    assert 'id="inspector-transition-between"' in html
    assert "data-source-in" in html
    assert "data-source-out" in html
    assert "studio-clip-playing-label" in html
    assert "studio-clip-resize" not in html
    assert "studio-music-handle" not in html
    assert "studio-track-voice" not in html
    assert "Voice-over" not in html
    assert "Duration editing later" not in html
    root = Path(__file__).resolve().parents[1]
    css = (root / "src" / "orga_drone" / "static" / "css" / "app.css").read_text(
        encoding="utf-8"
    )
    chip = css.split(".studio-transition-chip {", 1)[1].split("}", 1)[0]
    assert "font-size: 0;" not in chip
    assert "font-size: 0.62rem" in chip
    assert ".studio-clip.is-selected" in css
    assert ".studio-clip.is-active" in css
    assert ".studio-clip.is-selected,\n.studio-clip.is-active" not in css
    js = (root / "src" / "orga_drone" / "static" / "js" / "studio.js").read_text(
        encoding="utf-8"
    )
    assert "function playheadTouchesClip" in js
    assert "seekTimeS" in js
    assert "function fillEmptyInspector" in js
    assert "function refreshTransitionChrome" in js
    assert 'aria-label", "Transition"' not in js
    select_src = js.split("function selectClip", 1)[1].split("function canCutAtHit", 1)[0]
    assert "playheadTouchesClip" in select_src
    assert "syncPreviewMedia({ seek: true })" in select_src
    assert "studio-clip-playing-label\" hidden" in html or 'studio-clip-playing-label" hidden' in html
    grid = html.split('id="studio-grid"', 1)[1].split("</ol>", 1)[0]
    assert "Crossfade" in grid or "Cut" in grid or "Fade" in grid or "Schnitt" in grid
