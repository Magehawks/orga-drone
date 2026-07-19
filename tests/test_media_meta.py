"""Smoke tests for media_meta (stars, favorites, tags, notes)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key, parse_tags


def _seed_media(db: Database, root_path: Path) -> int:
    root_path.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root_path, label="test")
    media_file = root_path / "DJI_0001.MP4"
    media_file.write_bytes(b"fake")
    path = str(media_file.resolve())
    mid = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": "DJI_0001.MP4",
            "path": path,
            "size_bytes": 4,
            "duration_s": 12.0,
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
    return mid


def test_parse_tags_dedupes() -> None:
    assert parse_tags("alpha, Beta; alpha") == ["alpha", "Beta"]


def test_meta_survives_clear_root_media(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(db, tmp_path / "lib")
    item = db.get_media(mid)
    assert item is not None

    db.upsert_media_meta(
        item.path,
        stars=4,
        favorite=True,
        tags=["sunset", "beach"],
        notes="golden hour",
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
    )

    root_id = item.root_id
    db.clear_root_media(root_id)

    assert db.get_media(mid) is None
    with db.connect() as conn:
        row = conn.execute(
            "SELECT stars, favorite, tags_json, notes FROM media_meta WHERE media_path = ?",
            (item.path,),
        ).fetchone()
    assert row is not None
    assert int(row["stars"]) == 4
    assert int(row["favorite"]) == 1
    assert "sunset" in row["tags_json"]
    assert row["notes"] == "golden hour"

    mid2 = db.upsert_media(
        {
            "root_id": db.add_root(tmp_path / "lib", label="test"),
            "primary_asset_id": None,
            "kind": "video",
            "filename": "DJI_0001.MP4",
            "path": item.path,
            "size_bytes": 4,
            "duration_s": 12.0,
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
    db.link_media_meta_for_path(
        item.path,
        filename="DJI_0001.MP4",
        size_bytes=4,
        recorded_at="2024-01-02T10:00:00",
    )
    restored = db.get_media(mid2)
    assert restored is not None
    assert restored.stars == 4
    assert restored.favorite is True
    assert restored.tags == ["sunset", "beach"]
    assert restored.notes == "golden hour"


def test_list_search_tags_notes_and_favorite(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(db, tmp_path / "lib")
    item = db.get_media(mid)
    assert item is not None
    db.upsert_media_meta(
        item.path,
        stars=5,
        favorite=True,
        tags=["waterfall"],
        notes="look for mist",
    )

    by_tag = db.list_media(q="waterfall")
    assert len(by_tag) == 1
    by_notes = db.list_media(q="mist")
    assert len(by_notes) == 1
    favs = db.list_media(favorite=True)
    assert len(favs) == 1
    assert favs[0].stars == 5
    none = db.list_media(q="no-such-tag")
    assert none == []


def test_repath_media_meta(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(db, tmp_path / "lib")
    item = db.get_media(mid)
    assert item is not None
    db.upsert_media_meta(item.path, stars=3, favorite=False, tags=["x"], notes="y")
    new_path = str((tmp_path / "lib" / "renamed.MP4").resolve())
    db.repath_file(item.path, new_path)
    moved = db.find_media_by_path(new_path)
    assert moved is not None
    assert moved.stars == 3
    assert moved.notes == "y"


def test_http_meta_save(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    mid = _seed_media(db, tmp_path / "lib")

    client = TestClient(app)
    resp = client.post(
        f"/media/{mid}/meta",
        data={
            "stars": "2",
            "favorite": "1",
            "tags": "alpha, beta",
            "notes": "hello note",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "meta_saved" in resp.headers["location"]

    item = db.get_media(mid)
    assert item is not None
    assert item.stars == 2
    assert item.favorite is True
    assert item.tags == ["alpha", "beta"]
    assert item.notes == "hello note"

    listed = client.get("/?favorite=yes&q=hello")
    assert listed.status_code == 200
    assert "DJI_0001.MP4" in listed.text
    assert "★" in listed.text or "alpha" in listed.text

    detail = client.get(f"/media/{mid}")
    assert detail.status_code == 200
    assert "hello note" in detail.text
