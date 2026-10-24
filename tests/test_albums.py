"""Library albums: local references, independent of Studio projects."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.i18n import clear_catalog_cache
from orga_drone.scan import scan_root


def _jpeg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), (20, 40, 60)).save(path, format="JPEG")


def _index(db: Database, root: Path) -> None:
    root_id = db.add_root(root, label=root.name)
    scan_root(db, root_id, root)


def _studio_counts(db: Database) -> tuple[int, int]:
    with db.connect() as conn:
        projects = int(conn.execute("SELECT COUNT(*) AS n FROM studio_projects").fetchone()["n"])
        clips = int(conn.execute("SELECT COUNT(*) AS n FROM studio_clips").fetchone()["n"])
    return projects, clips


def test_create_rename_delete_and_multi_album(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    lib_a = tmp_path / "card-a"
    lib_b = tmp_path / "card-b"
    photo_a = lib_a / "vacation.jpg"
    photo_b = lib_b / "action.jpg"
    _jpeg(photo_a)
    _jpeg(photo_b)
    before_a = photo_a.read_bytes()
    before_b = photo_b.read_bytes()
    _index(db, lib_a)
    _index(db, lib_b)
    media_a = db.find_media_by_path(str(photo_a.resolve()))
    media_b = db.find_media_by_path(str(photo_b.resolve()))
    assert media_a is not None and media_b is not None
    db.upsert_media_meta(
        media_a.path,
        stars=4,
        favorite=True,
        tags=["coast"],
        notes="keep me",
        identity_key=make_identity_key(
            media_a.filename, media_a.size_bytes, media_a.recorded_at
        ),
    )
    studio = db.create_studio_project("Story stays")
    db.add_studio_item(
        media_a.path,
        identity_key=make_identity_key(
            media_a.filename, media_a.size_bytes, media_a.recorded_at
        ),
        filename=media_a.filename,
        recorded_at=media_a.recorded_at,
        kind=media_a.kind,
        project_id=studio.id,
        source_media_id=media_a.id,
    )
    studio_before = _studio_counts(db)

    with pytest.raises(ValueError):
        db.create_album("   ")

    malta = db.create_album("  Malta   vacation  ")
    assert malta.title == "Malta vacation"
    renamed = db.rename_album(malta.id, "Malta 2024")
    assert renamed is not None
    assert renamed.title == "Malta 2024"
    cliffs = db.create_album("Cliffs")

    assert db.add_media_to_album(malta.id, media_a.id) == "added"
    assert db.add_media_to_album(malta.id, media_a.id) == "exists"
    assert db.add_media_to_album(cliffs.id, media_a.id) == "added"
    assert db.add_media_to_album(cliffs.id, media_b.id) == "added"
    titles = {album.title for album in db.albums_for_path(media_a.path)}
    assert titles == {"Malta 2024", "Cliffs"}
    assert photo_a.read_bytes() == before_a
    assert photo_b.read_bytes() == before_b
    assert _studio_counts(db) == studio_before
    kept = db.get_studio_project(studio.id)
    assert kept is not None
    assert kept.title == "Story stays"

    listed = db.list_album_items(malta.id)
    assert len(listed) == 1
    assert listed[0].state == "available"
    assert listed[0].media_id == media_a.id
    assert listed[0].filename == "vacation.jpg"

    photo_a.unlink()
    offline = db.list_album_items(malta.id)
    assert len(offline) == 1
    assert offline[0].filename == "vacation.jpg"
    assert offline[0].state == "offline"
    assert offline[0].media_id is None

    _index(db, lib_a)
    _index(db, lib_b)
    after_scan = db.list_album_items(malta.id)
    assert len(after_scan) == 1
    assert after_scan[0].state == "offline"
    assert after_scan[0].filename == "vacation.jpg"
    cliffs_items = db.list_album_items(cliffs.id)
    assert {item.filename for item in cliffs_items} == {"vacation.jpg", "action.jpg"}
    action = next(item for item in cliffs_items if item.filename == "action.jpg")
    assert action.state == "available"
    assert action.media_id is not None
    restored = db.get_media(action.media_id)
    assert restored is not None
    vacation_meta = db.find_media_by_path(str(photo_a.resolve()))
    assert vacation_meta is None
    with db.connect() as conn:
        meta = conn.execute(
            "SELECT stars, notes, tags_json FROM media_meta WHERE media_path = ?",
            (str(photo_a.resolve()),),
        ).fetchone()
    assert meta is not None
    assert int(meta["stars"]) == 4
    assert meta["notes"] == "keep me"
    assert "coast" in meta["tags_json"]
    assert _studio_counts(db) == studio_before

    assert db.remove_media_from_album(cliffs.id, media_b.path) is True
    remaining = db.list_album_items(cliffs.id)
    assert [item.filename for item in remaining] == ["vacation.jpg"]
    assert db.delete_album(malta.id) is True
    assert db.get_album(malta.id) is None
    assert db.list_album_items(malta.id) == []
    assert photo_b.read_bytes() == before_b
    assert db.get_media(action.media_id) is not None


def test_album_reference_follows_rescan_when_file_returns(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    lib = tmp_path / "lib"
    photo = lib / "return.jpg"
    _jpeg(photo)
    _index(db, lib)
    media = db.find_media_by_path(str(photo.resolve()))
    assert media is not None
    album = db.create_album("Return")
    assert db.add_media_to_album(album.id, media.id) == "added"
    original_id = media.id
    db.clear_root_media(media.root_id)
    assert db.get_media(original_id) is None
    held = db.list_album_items(album.id)
    assert len(held) == 1
    assert held[0].state == "available"
    assert held[0].media_id is None
    _index(db, lib)
    again = db.find_media_by_path(str(photo.resolve()))
    assert again is not None
    assert again.id != original_id
    linked = db.list_album_items(album.id)
    assert len(linked) == 1
    assert linked[0].state == "available"
    assert linked[0].media_id == again.id
    assert linked[0].filename == "return.jpg"


def test_http_album_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_catalog_cache()
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    lib = tmp_path / "lib"
    photo = lib / "DJI_0001.JPG"
    _jpeg(photo)
    payload = photo.read_bytes()
    _index(db, lib)
    media = db.find_media_by_path(str(photo.resolve()))
    assert media is not None
    studio_before = _studio_counts(db)

    client = TestClient(app)
    client.cookies.set("lang", "en")

    empty = client.get("/albums")
    assert empty.status_code == 200
    assert "No albums yet" in empty.text
    assert "Create album" in empty.text
    assert 'href="/albums"' in empty.text

    german = TestClient(app).get("/albums")
    assert german.status_code == 200
    assert "Album anlegen" in german.text

    invalid = client.post("/albums", data={"title": "   "}, follow_redirects=False)
    assert invalid.status_code == 303
    assert invalid.headers["location"].endswith("msg=album_invalid")

    created = client.post(
        f"/media/{media.id}/albums/add",
        data={"title": "Harbor"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert "msg=album_added" in created.headers["location"]
    assert photo.read_bytes() == payload

    detail = client.get(created.headers["location"])
    assert detail.status_code == 200
    assert "Harbor" in detail.text
    assert "Added to album." in detail.text
    assert "separate from Studio projects" in detail.text

    albums = db.list_albums()
    assert len(albums) == 1
    album_id = albums[0].id
    page = client.get(f"/albums/{album_id}")
    assert page.status_code == 200
    assert "DJI_0001.JPG" in page.text
    assert "Available" in page.text
    assert f"/media/{media.id}" in page.text

    second = client.post("/albums", data={"title": "Evening"}, follow_redirects=False)
    assert second.status_code == 303
    evening = db.list_albums()
    evening_id = next(album.id for album in evening if album.title == "Evening")
    added = client.post(
        f"/media/{media.id}/albums/add",
        data={"album_id": str(evening_id)},
        follow_redirects=False,
    )
    assert added.status_code == 303
    assert "msg=album_added" in added.headers["location"]
    assert {album.title for album in db.albums_for_path(media.path)} == {"Harbor", "Evening"}

    renamed = client.post(
        f"/albums/{album_id}/rename",
        data={"title": "Harbor morning"},
        follow_redirects=False,
    )
    assert renamed.status_code == 303
    renamed_album = db.get_album(album_id)
    assert renamed_album is not None
    assert renamed_album.title == "Harbor morning"

    photo.unlink()
    offline_page = client.get(f"/albums/{album_id}")
    assert offline_page.status_code == 200
    assert "DJI_0001.JPG" in offline_page.text
    assert "Offline" in offline_page.text
    assert "File is not on this computer right now." in offline_page.text

    removed = client.post(
        f"/albums/{evening_id}/items/{db.list_album_items(evening_id)[0].id}/remove",
        follow_redirects=False,
    )
    assert removed.status_code == 303
    assert db.list_album_items(evening_id) == []

    deleted = client.post(
        f"/albums/{album_id}/delete",
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert db.get_album(album_id) is None
    assert _studio_counts(db) == studio_before
    missing = client.get(f"/albums/{album_id}")
    assert missing.status_code == 404
