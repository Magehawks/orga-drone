"""Studio workspace: persistence, relink, HTTP, nav, Browse add markup."""

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
    filename: str = "DJI_0001.MP4",
    size_bytes: int = 4,
    recorded_at: str = "2024-01-02T10:00:00",
    content: bytes = b"fake",
    kind: str = "video",
    duration_s: float | None = 12.0,
) -> int:
    root_path.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root_path, label="test")
    media_file = root_path / filename
    media_file.write_bytes(content)
    path = str(media_file.resolve())
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": kind,
            "filename": filename,
            "path": path,
            "size_bytes": size_bytes,
            "duration_s": duration_s,
            "recorded_at": recorded_at,
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


def _add_item(db: Database, media_id: int) -> tuple[int, bool]:
    item = db.get_media(media_id)
    assert item is not None
    return db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
    )


def test_add_remove_clear_and_append_order(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid_a = _seed_media(db, tmp_path / "lib", filename="A.MP4", content=b"aaaa")
    mid_b = _seed_media(db, tmp_path / "lib", filename="B.MP4", content=b"bbbb")
    mid_c = _seed_media(db, tmp_path / "lib", filename="C.MP4", content=b"cccc")

    id_a, created_a = _add_item(db, mid_a)
    id_b, created_b = _add_item(db, mid_b)
    id_c, created_c = _add_item(db, mid_c)
    assert created_a and created_b and created_c

    again_id, created_again = _add_item(db, mid_a)
    assert again_id == id_a
    assert created_again is False

    items = db.list_studio_items()
    assert [i.id for i in items] == [id_a, id_b, id_c]
    assert [i.position for i in items] == [1, 2, 3]
    assert all(i.available for i in items)

    assert db.remove_studio_item(id_b) is True
    assert db.remove_studio_item(id_b) is False
    remaining = db.list_studio_items()
    assert [i.id for i in remaining] == [id_a, id_c]

    cleared = db.clear_studio()
    assert cleared == 2
    assert db.list_studio_items() == []


def test_studio_survives_clear_root_and_path_relink(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(db, tmp_path / "lib")
    item = db.get_media(mid)
    assert item is not None
    studio_id, _ = _add_item(db, mid)

    root_id = item.root_id
    db.clear_root_media(root_id)
    after_clear = db.list_studio_items()
    assert len(after_clear) == 1
    assert after_clear[0].id == studio_id
    assert after_clear[0].available is False
    assert after_clear[0].filename == "DJI_0001.MP4"
    assert after_clear[0].recorded_at == "2024-01-02T10:00:00"
    assert after_clear[0].media_id is None

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
    db.link_studio_item_for_path(
        item.path,
        filename="DJI_0001.MP4",
        size_bytes=4,
        recorded_at="2024-01-02T10:00:00",
    )
    restored = db.list_studio_items()
    assert len(restored) == 1
    assert restored[0].available is True
    assert restored[0].media_id == mid2
    assert restored[0].id == studio_id


def test_unique_identity_key_relink(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    mid = _seed_media(db, old_dir, filename="SAME.MP4", content=b"data")
    item = db.get_media(mid)
    assert item is not None
    studio_id, _ = _add_item(db, mid)

    db.clear_root_media(item.root_id)
    assert db.list_studio_items()[0].available is False

    new_file = new_dir / "SAME.MP4"
    new_dir.mkdir(parents=True, exist_ok=True)
    new_file.write_bytes(b"data")
    new_path = str(new_file.resolve())
    mid2 = db.upsert_media(
        {
            "root_id": db.add_root(new_dir, label="new"),
            "primary_asset_id": None,
            "kind": "video",
            "filename": "SAME.MP4",
            "path": new_path,
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
    db.link_studio_item_for_path(
        new_path,
        filename="SAME.MP4",
        size_bytes=4,
        recorded_at="2024-01-02T10:00:00",
    )
    linked = db.list_studio_items()
    assert len(linked) == 1
    assert linked[0].id == studio_id
    assert linked[0].available is True
    assert linked[0].media_id == mid2
    assert linked[0].media_path == new_path


def test_ambiguous_identity_key_stays_unavailable(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    lib_a = tmp_path / "a"
    lib_b = tmp_path / "b"
    mid_a = _seed_media(db, lib_a, filename="SAME.MP4", content=b"xxxx")
    mid_b = _seed_media(db, lib_b, filename="SAME.MP4", content=b"xxxx")
    item_a = db.get_media(mid_a)
    item_b = db.get_media(mid_b)
    assert item_a is not None and item_b is not None
    assert make_identity_key(
        item_a.filename, item_a.size_bytes, item_a.recorded_at
    ) == make_identity_key(item_b.filename, item_b.size_bytes, item_b.recorded_at)

    id_a, _ = _add_item(db, mid_a)
    id_b, _ = _add_item(db, mid_b)
    db.clear_root_media(item_a.root_id)
    db.clear_root_media(item_b.root_id)
    assert all(not i.available for i in db.list_studio_items())

    new_dir = tmp_path / "reappear"
    new_file = new_dir / "SAME.MP4"
    new_dir.mkdir(parents=True, exist_ok=True)
    new_file.write_bytes(b"xxxx")
    new_path = str(new_file.resolve())
    db.upsert_media(
        {
            "root_id": db.add_root(new_dir, label="new"),
            "primary_asset_id": None,
            "kind": "video",
            "filename": "SAME.MP4",
            "path": new_path,
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
    db.link_studio_item_for_path(
        new_path,
        filename="SAME.MP4",
        size_bytes=4,
        recorded_at="2024-01-02T10:00:00",
    )
    items = {i.id: i for i in db.list_studio_items()}
    assert items[id_a].available is False
    assert items[id_b].available is False
    assert items[id_a].media_path != new_path
    assert items[id_b].media_path != new_path


def test_repath_studio_after_rename(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(db, tmp_path / "lib", filename="OLD.MP4")
    item = db.get_media(mid)
    assert item is not None
    studio_id, _ = _add_item(db, mid)

    new_path = str((tmp_path / "lib" / "NEW.MP4").resolve())
    db.repath_file(item.path, new_path, new_stem="NEW")
    linked = db.list_studio_items()
    assert len(linked) == 1
    assert linked[0].id == studio_id
    assert linked[0].media_path == new_path
    assert linked[0].available is True


def test_studio_independent_from_favorites(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(db, tmp_path / "lib")
    item = db.get_media(mid)
    assert item is not None
    db.upsert_media_meta(
        item.path,
        favorite=True,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
    )
    assert db.is_in_studio(item.path) is False
    _add_item(db, mid)
    assert db.is_in_studio(item.path) is True
    favs = db.list_media(favorite=True)
    assert len(favs) == 1
    db.clear_studio()
    favs_after = db.list_media(favorite=True)
    assert len(favs_after) == 1
    assert favs_after[0].favorite is True


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    return TestClient(create_app())


def test_http_studio_empty_and_nav(client: TestClient) -> None:
    r = client.get("/studio")
    assert r.status_code == 200
    body = r.text
    assert 'href="/studio"' in body
    assert "Your story is empty" in body or "Deine Geschichte ist leer" in body
    assert "studio-creator" in body
    assert "studio-story-track" in body or "Story" in body
    assert "studio-export-dialog" in body
    assert "Voice-over" in body or "coming later" in body or "folgt später" in body
    assert 'class="bottom-nav"' in body
    bottom = body.split('class="bottom-nav"', 1)[1].split("</nav>", 1)[0]
    assert "/studio" in bottom
    assert "/duplicates" not in bottom
    primary = body.split('class="primary-nav"', 1)[1].split("</nav>", 1)[0]
    assert "/duplicates" in primary
    assert "/studio" in primary


def test_http_studio_creator_shell_with_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    mid_a = _seed_media(db, tmp_path / "lib", filename="A.MP4", content=b"aaaa")
    mid_b = _seed_media(
        db,
        tmp_path / "lib",
        filename="B.JPG",
        content=b"bbbb",
        kind="photo",
        duration_s=None,
    )
    _add_item(db, mid_a)
    _add_item(db, mid_b)
    c = TestClient(app)
    page = c.get("/studio")
    assert page.status_code == 200
    html = page.text
    assert "studio-creator" in html
    assert "studio-preview" in html
    assert "studio-transport" in html
    assert "studio-inspector" in html
    assert "studio-music-track" in html
    assert "studio-track-voice" in html
    assert "studio-playhead" in html
    assert "studio-transition" in html
    assert "A.MP4" in html
    assert "B.JPG" in html
    assert "studio.js" in html
    assert 'id="studio-export-dialog"' in html
    assert "not available yet" in html or "noch nicht verfügbar" in html


def test_http_add_remove_and_browse_markup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    mid = _seed_media(db, tmp_path / "lib2")
    c = TestClient(app)

    add = c.post(
        f"/media/{mid}/studio/add",
        data={"return_to": "detail"},
        follow_redirects=False,
    )
    assert add.status_code == 303
    assert add.headers["location"] == f"/media/{mid}?msg=studio_added"

    again = c.post(
        f"/media/{mid}/studio/add",
        data={"return_to": "detail"},
        follow_redirects=False,
    )
    assert again.status_code == 303
    assert "studio_already" in again.headers["location"]

    studio = c.get("/studio")
    assert studio.status_code == 200
    assert "DJI_0001.MP4" in studio.text
    assert f"/media/{mid}" in studio.text

    items = db.list_studio_items()
    assert len(items) == 1
    sid = items[0].id

    remove = c.post(f"/studio/{sid}/remove", follow_redirects=False)
    assert remove.status_code == 303
    assert remove.headers["location"].startswith("/studio")
    assert db.list_studio_items() == []

    _add_item(db, mid)
    clear = c.post("/studio/clear", follow_redirects=False)
    assert clear.status_code == 303
    assert clear.headers["location"].startswith("/studio")
    assert db.list_studio_items() == []

    browse = c.get("/browse")
    assert browse.status_code == 200
    html = browse.text
    assert f'action="/media/{mid}/studio/add"' in html
    assert 'name="return_to" value="/browse?' in html
    assert '<a class="card"' not in html
    assert 'class="card"' in html
    assert 'class="card-main"' in html

    add_browse = c.post(
        f"/media/{mid}/studio/add",
        data={"return_to": "/browse?favorite=yes&page=2"},
        follow_redirects=False,
    )
    assert add_browse.status_code == 303
    assert add_browse.headers["location"] == "/browse?favorite=yes&page=2"

    plain_browse = c.post(
        f"/media/{mid}/studio/add",
        data={"return_to": "browse"},
        follow_redirects=False,
    )
    assert plain_browse.status_code == 303
    assert plain_browse.headers["location"] == "/browse"

    bad = c.post(
        f"/media/{mid}/studio/add",
        data={"return_to": "https://evil.example/"},
        follow_redirects=False,
    )
    assert bad.status_code == 303
    assert bad.headers["location"].startswith(f"/media/{mid}")


def test_reorder_persists_and_survives_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "t.sqlite3"
    db = Database(db_path)
    mid_a = _seed_media(db, tmp_path / "lib", filename="A.MP4", content=b"aaaa")
    mid_b = _seed_media(db, tmp_path / "lib", filename="B.MP4", content=b"bbbb")
    mid_c = _seed_media(db, tmp_path / "lib", filename="C.MP4", content=b"cccc")
    id_a, _ = _add_item(db, mid_a)
    id_b, _ = _add_item(db, mid_b)
    id_c, _ = _add_item(db, mid_c)

    db.reorder_studio_items([id_c, id_a, id_b])
    assert [i.id for i in db.list_studio_items()] == [id_c, id_a, id_b]
    assert [i.position for i in db.list_studio_items()] == [1, 2, 3]

    reopened = Database(db_path)
    assert [i.id for i in reopened.list_studio_items()] == [id_c, id_a, id_b]


def test_reorder_rejects_non_permutation(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid_a = _seed_media(db, tmp_path / "lib", filename="A.MP4", content=b"a")
    mid_b = _seed_media(db, tmp_path / "lib", filename="B.MP4", content=b"b")
    id_a, _ = _add_item(db, mid_a)
    id_b, _ = _add_item(db, mid_b)
    with pytest.raises(ValueError):
        db.reorder_studio_items([id_a])
    with pytest.raises(ValueError):
        db.reorder_studio_items([id_a, id_a])
    with pytest.raises(ValueError):
        db.reorder_studio_items([id_a, id_b, 999])


def test_order_and_photo_duration_survive_clear_and_relink(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid_photo = _seed_media(
        db,
        tmp_path / "lib",
        filename="P.JPG",
        content=b"photo",
        kind="photo",
        duration_s=None,
        size_bytes=5,
    )
    mid_video = _seed_media(
        db,
        tmp_path / "lib",
        filename="V.MP4",
        content=b"video",
        kind="video",
        duration_s=20.0,
        size_bytes=5,
    )
    id_p, _ = _add_item(db, mid_photo)
    id_v, _ = _add_item(db, mid_video)
    db.reorder_studio_items([id_v, id_p])
    db.set_studio_photo_duration(id_p, 5.5)

    photo = db.get_media(mid_photo)
    video = db.get_media(mid_video)
    assert photo is not None and video is not None
    root_id = photo.root_id
    db.clear_root_media(root_id)

    after = db.list_studio_items()
    assert [i.id for i in after] == [id_v, id_p]
    assert after[1].photo_duration_s == 5.5
    assert after[1].kind_snapshot == "photo"
    assert after[0].kind_snapshot == "video"
    assert after[1].kind == "photo"
    assert after[0].available is False

    db.upsert_media(
        {
            "root_id": db.add_root(tmp_path / "lib", label="test"),
            "primary_asset_id": None,
            "kind": "photo",
            "filename": "P.JPG",
            "path": photo.path,
            "size_bytes": 5,
            "duration_s": None,
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
    db.link_studio_item_for_path(
        photo.path,
        filename="P.JPG",
        size_bytes=5,
        recorded_at="2024-01-02T10:00:00",
    )
    restored = {i.id: i for i in db.list_studio_items()}
    assert [i.id for i in db.list_studio_items()] == [id_v, id_p]
    assert restored[id_p].photo_duration_s == 5.5
    assert restored[id_p].kind_snapshot == "photo"
    assert restored[id_p].available is True


def test_kind_snapshot_on_add_and_unavailable(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(
        db,
        tmp_path / "lib",
        filename="shot.jpg",
        content=b"img",
        kind="photo",
        duration_s=None,
    )
    sid, _ = _add_item(db, mid)
    item = db.list_studio_items()[0]
    assert item.kind_snapshot == "photo"
    assert item.kind == "photo"

    media = db.get_media(mid)
    assert media is not None
    db.clear_root_media(media.root_id)
    unavailable = db.list_studio_items()[0]
    assert unavailable.id == sid
    assert unavailable.available is False
    assert unavailable.kind_snapshot == "photo"
    assert unavailable.kind == "photo"


def test_photo_duration_clamp_and_reset(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(
        db,
        tmp_path / "lib",
        filename="p.jpg",
        content=b"p",
        kind="photo",
        duration_s=None,
    )
    sid, _ = _add_item(db, mid)
    low = db.set_studio_photo_duration(sid, 0.1)
    assert low.photo_duration_s == 0.5
    high = db.set_studio_photo_duration(sid, 99.0)
    assert high.photo_duration_s == 60.0
    reset = db.set_studio_photo_duration(sid, None)
    assert reset.photo_duration_s is None

    vid = _seed_media(
        db,
        tmp_path / "lib",
        filename="v.mp4",
        content=b"v",
        kind="video",
        duration_s=8.0,
    )
    vid_sid, _ = _add_item(db, vid)
    with pytest.raises(ValueError):
        db.set_studio_photo_duration(vid_sid, 3.0)


def test_http_reorder_and_photo_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    mid_a = _seed_media(
        db, tmp_path / "lib", filename="A.jpg", content=b"a", kind="photo", duration_s=None
    )
    mid_b = _seed_media(
        db, tmp_path / "lib", filename="B.mp4", content=b"b", kind="video", duration_s=10.0
    )
    id_a, _ = _add_item(db, mid_a)
    id_b, _ = _add_item(db, mid_b)
    c = TestClient(app)

    page = c.get("/studio")
    assert page.status_code == 200
    assert "00:00:13" in page.text or "studio-transport-time" in page.text
    assert "studio.js" in page.text
    assert "studio-clip" in page.text

    bad = c.post("/api/studio/reorder", json={"ordered_ids": [id_a]})
    assert bad.status_code == 400

    ok = c.post("/api/studio/reorder", json={"ordered_ids": [id_b, id_a]})
    assert ok.status_code == 200
    body = ok.json()
    assert body["ok"] is True
    assert body["ordered_ids"] == [id_b, id_a]
    assert body["summary"]["photo_count"] == 1
    assert body["summary"]["video_count"] == 1
    assert [i.id for i in db.list_studio_items()] == [id_b, id_a]

    patch_ok = c.patch(
        f"/api/studio/{id_a}/photo-duration",
        json={"duration_s": 7.25},
    )
    assert patch_ok.status_code == 200
    assert patch_ok.json()["photo_duration_s"] == 7.25
    assert db.list_studio_items()[1].photo_duration_s == 7.25

    reset = c.patch(
        f"/api/studio/{id_a}/photo-duration",
        json={"duration_s": None},
    )
    assert reset.status_code == 200
    assert reset.json()["photo_duration_s"] is None

    video_patch = c.patch(
        f"/api/studio/{id_b}/photo-duration",
        json={"duration_s": 4.0},
    )
    assert video_patch.status_code == 400

    clamp = c.patch(
        f"/api/studio/{id_a}/photo-duration",
        json={"duration_s": 0.01},
    )
    assert clamp.status_code == 200
    assert clamp.json()["photo_duration_s"] == 0.5
