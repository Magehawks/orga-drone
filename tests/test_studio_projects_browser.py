"""Studio multi-project browser and switching (Issue #19)."""

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


def _add_clip(db: Database, media_id: int, project_id: int) -> int:
    item = db.get_media(media_id)
    assert item is not None
    clip_id, _ = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(
            item.filename, item.size_bytes, item.recorded_at
        ),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
        project_id=project_id,
        source_media_id=media_id,
    )
    return clip_id


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def test_fresh_db_has_no_default_project(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    assert db.list_studio_projects() == []
    assert db.get_open_studio_project() is None
    assert db.resolve_studio_page_project() is None
    reopened = Database(tmp_path / "t.sqlite3")
    assert reopened.list_studio_projects() == []


def test_multiple_projects_persist_and_stay_isolated(tmp_path: Path) -> None:
    db_path = tmp_path / "t.sqlite3"
    db = Database(db_path)
    mid_a = _seed_media(db, tmp_path / "lib", filename="A.MP4", content=b"aaaa")
    mid_b = _seed_media(db, tmp_path / "lib", filename="B.MP4", content=b"bbbb")
    item_a = db.get_media(mid_a)
    item_b = db.get_media(mid_b)
    assert item_a is not None and item_b is not None
    before_a = Path(item_a.path).read_bytes()
    before_b = Path(item_b.path).read_bytes()

    project_a = db.create_studio_project("Alps morning")
    project_b = db.create_studio_project("Lake evening")
    clip_a = _add_clip(db, mid_a, project_a.id)
    clip_b = _add_clip(db, mid_b, project_b.id)

    assert [c.id for c in db.list_studio_items(project_a.id)] == [clip_a]
    assert [c.id for c in db.list_studio_items(project_b.id)] == [clip_b]

    db2 = Database(db_path)
    titles = {p.title for p in db2.list_studio_projects()}
    assert titles == {"Alps morning", "Lake evening"}
    assert [c.id for c in db2.list_studio_items(project_a.id)] == [clip_a]
    assert [c.id for c in db2.list_studio_items(project_b.id)] == [clip_b]
    assert Path(item_a.path).read_bytes() == before_a
    assert Path(item_b.path).read_bytes() == before_b


def test_list_orders_by_updated_at_not_export_or_open(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    a = db.create_studio_project("A")
    b = db.create_studio_project("B")
    with db.connect() as conn:
        conn.execute(
            "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
            ("2026-01-01T00:00:00", a.id),
        )
        conn.execute(
            "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
            ("2026-01-02T00:00:00", b.id),
        )
    listed = db.list_studio_projects()
    assert [p.id for p in listed] == [b.id, a.id]

    db.set_studio_project_title(a.id, "A renamed")
    with db.connect() as conn:
        conn.execute(
            "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
            ("2026-01-03T00:00:00", a.id),
        )
    listed = db.list_studio_projects()
    assert listed[0].id == a.id
    assert listed[0].title == "A renamed"

    before = db.get_studio_project(a.id)
    assert before is not None
    db.set_open_studio_project_id(b.id)
    after_open = db.get_studio_project(a.id)
    assert after_open is not None
    assert after_open.updated_at == before.updated_at


def test_remove_clip_updates_project_timestamp(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(db, tmp_path / "lib")
    project = db.create_studio_project("Touch")
    with db.connect() as conn:
        conn.execute(
            "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
            ("2020-01-01T00:00:00", project.id),
        )
    clip_id = _add_clip(db, mid, project.id)
    after_add = db.get_studio_project(project.id)
    assert after_add is not None
    assert after_add.updated_at != "2020-01-01T00:00:00"
    with db.connect() as conn:
        conn.execute(
            "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
            ("2020-01-01T00:00:00", project.id),
        )
    assert db.remove_studio_item(clip_id) is True
    after_remove = db.get_studio_project(project.id)
    assert after_remove is not None
    assert after_remove.updated_at != "2020-01-01T00:00:00"
    item = db.get_media(mid)
    assert item is not None
    assert Path(item.path).is_file()


def test_last_opened_survives_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "t.sqlite3"
    db = Database(db_path)
    a = db.create_studio_project("A")
    b = db.create_studio_project("B")
    db.set_open_studio_project_id(b.id)
    assert db.get_open_studio_project() is not None
    assert db.get_open_studio_project().id == b.id

    db2 = Database(db_path)
    opened = db2.get_open_studio_project()
    assert opened is not None
    assert opened.id == b.id
    assert opened.id != a.id


def test_missing_last_opened_restores_most_recent(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    a = db.create_studio_project("Older")
    b = db.create_studio_project("Newer")
    with db.connect() as conn:
        conn.execute(
            "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
            ("2026-01-01T00:00:00", a.id),
        )
        conn.execute(
            "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
            ("2026-01-02T00:00:00", b.id),
        )
    restored = db.resolve_studio_page_project()
    assert restored is not None
    assert restored.id == b.id
    assert db.get_open_studio_project() is not None
    assert db.get_open_studio_project().id == b.id


def test_rename_does_not_touch_source_files(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(db, tmp_path / "lib")
    item = db.get_media(mid)
    assert item is not None
    path = Path(item.path)
    before = path.read_bytes()
    project = db.create_studio_project("Temp")
    _add_clip(db, mid, project.id)
    db.set_studio_project_title(project.id, "Renamed flight")
    loaded = db.get_studio_project(project.id)
    assert loaded is not None
    assert loaded.title == "Renamed flight"
    assert path.read_bytes() == before
    assert path.name == "DJI_0001.MP4"
    assert db.get_media(mid) is not None


def test_delete_project_leaves_media_and_shows_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, db = _client(tmp_path, monkeypatch)
    mid = _seed_media(db, tmp_path / "lib")
    item = db.get_media(mid)
    assert item is not None
    path = Path(item.path)
    keep = db.create_studio_project("Keep")
    doomed = db.create_studio_project("Doomed")
    _add_clip(db, mid, doomed.id)
    db.set_open_studio_project_id(doomed.id)

    deleted = c.delete(f"/api/studio/projects/{doomed.id}")
    assert deleted.status_code == 200
    assert db.get_studio_project(doomed.id) is None
    assert db.list_studio_items(doomed.id) == []
    assert db.get_media(mid) is not None
    assert path.is_file()
    remaining = {p.id for p in db.list_studio_projects()}
    assert keep.id in remaining
    assert doomed.id not in remaining

    page = c.get("/studio")
    assert page.status_code == 200
    assert 'data-studio-mode="browser"' in page.text
    assert "Keep" in page.text
    assert "Switch, create, or manage Studio projects" in page.text or (
        "Wechsle, erstelle oder verwalte Studio-Projekte" in page.text
    )


def test_delete_last_project_does_not_recreate_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, db = _client(tmp_path, monkeypatch)
    mid = _seed_media(db, tmp_path / "lib")
    item = db.get_media(mid)
    assert item is not None
    path = Path(item.path)
    only = db.create_studio_project("Only")
    _add_clip(db, mid, only.id)
    db.set_open_studio_project_id(only.id)
    assert c.delete(f"/api/studio/projects/{only.id}").status_code == 200

    page = c.get("/studio")
    assert page.status_code == 200
    assert 'data-studio-mode="browser"' in page.text
    assert "No Studio projects yet" in page.text or "Noch keine Studio-Projekte" in page.text
    assert db.list_studio_projects() == []
    assert db.get_media(mid) is not None
    assert path.is_file()

    db2 = Database(db.path)
    assert db2.list_studio_projects() == []


def test_http_project_api_list_create_open_update_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, db = _client(tmp_path, monkeypatch)
    empty = c.get("/api/studio/projects")
    assert empty.status_code == 200
    assert empty.json()["projects"] == []
    assert empty.json()["current_id"] is None

    created = c.post("/api/studio/projects", json={"title": "Flight A"})
    assert created.status_code == 201
    first_id = created.json()["id"]
    second = c.post("/api/studio/projects", json={"title": "Flight B"})
    second_id = second.json()["id"]

    listed = c.get("/api/studio/projects").json()
    titles = [p["title"] for p in listed["projects"]]
    assert "Flight A" in titles and "Flight B" in titles

    opened = c.post(f"/api/studio/projects/{second_id}/open")
    assert opened.status_code == 200
    assert opened.json()["id"] == second_id
    listed2 = c.get("/api/studio/projects").json()
    assert listed2["current_id"] == second_id

    mid = _seed_media(db, tmp_path / "lib")
    _add_clip(db, mid, second_id)
    page = c.get("/studio")
    assert page.status_code == 200
    assert f'data-project-id="{second_id}"' in page.text
    assert 'data-studio-mode="editor"' in page.text
    assert 'id="studio-projects-open"' in page.text
    after_creator = page.text.split('class="studio-creator"', 1)[1]
    assert 'id="studio-projects-dialog"' in after_creator
    assert 'data-project-open="' in after_creator
    title_cluster = after_creator.split("studio-topbar-title", 1)[1].split(
        "studio-topbar-actions", 1
    )[0]
    assert 'id="studio-projects-open"' in title_cluster
    assert 'id="studio-project-title"' in title_cluster
    assert "studio-project-identity-label" in title_cluster
    actions = after_creator.split("studio-topbar-actions", 1)[1].split(
        "</div>", 1
    )[0]
    assert 'id="studio-export-open"' in actions
    assert "studio-clear-form" not in actions
    assert 'id="studio-projects-open"' not in actions
    toolbar = after_creator.split("studio-timeline-toolbar", 1)[1].split(
        "studio-timeline-row", 1
    )[0]
    assert "studio-clear-form" in toolbar
    assert "Clear Studio" in toolbar or "Studio leeren" in toolbar
    assert "Remove all clips from this Story" in after_creator or (
        "Alle Clips aus dieser Story" in after_creator
    )
    assert "studio-project-current-badge" in after_creator
    assert "Switch, create, or manage Studio projects" in after_creator or (
        "Wechsle, erstelle oder verwalte Studio-Projekte" in after_creator
    )
    js = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "orga_drone"
        / "static"
        / "js"
        / "studio.js"
    ).read_text(encoding="utf-8")
    assert "flushPendingTitleSave" in js

    missing = c.post("/api/studio/projects/99999/open")
    assert missing.status_code == 404

    patched = c.patch(
        f"/api/studio/projects/{second_id}", json={"title": "Flight B edited"}
    )
    assert patched.status_code == 200
    assert db.get_studio_project(second_id).title == "Flight B edited"

    assert c.delete(f"/api/studio/projects/{first_id}").status_code == 200
    assert db.get_studio_project(first_id) is None


def test_add_without_open_project_redirects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, db = _client(tmp_path, monkeypatch)
    mid = _seed_media(db, tmp_path / "lib")
    add = c.post(
        f"/media/{mid}/studio/add",
        data={"return_to": "detail"},
        follow_redirects=False,
    )
    assert add.status_code == 303
    assert add.headers["location"] == "/studio?msg=studio_need_project"
    assert db.list_studio_projects() == []
    page = c.get("/studio?msg=studio_need_project")
    assert "Pick or create a Studio project" in page.text or (
        "Wähle oder erstelle ein Studio-Projekt" in page.text
    )


def test_add_and_browse_badge_are_scoped_to_open_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, db = _client(tmp_path, monkeypatch)
    mid = _seed_media(db, tmp_path / "lib")
    item = db.get_media(mid)
    assert item is not None
    a = db.create_studio_project("A")
    b = db.create_studio_project("B")
    open_b = c.get(f"/studio?project_id={b.id}", follow_redirects=False)
    assert open_b.status_code == 303

    add = c.post(
        f"/media/{mid}/studio/add",
        data={"return_to": "detail"},
        follow_redirects=False,
    )
    assert add.status_code == 303
    assert db.list_studio_items(a.id) == []
    clips_b = db.list_studio_items(b.id)
    assert len(clips_b) == 1
    assert clips_b[0].media_path == item.path

    browse = c.get("/browse")
    assert "In Studio" in browse.text or "Im Studio" in browse.text

    c.get(f"/studio?project_id={a.id}")
    browse_a = c.get("/browse")
    assert f'action="/media/{mid}/studio/add"' in browse_a.text
    assert "In Studio" not in browse_a.text and "Im Studio" not in browse_a.text


def test_clear_only_affects_open_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, db = _client(tmp_path, monkeypatch)
    mid_a = _seed_media(db, tmp_path / "lib", filename="A.MP4", content=b"a")
    mid_b = _seed_media(db, tmp_path / "lib", filename="B.MP4", content=b"b")
    a = db.create_studio_project("A")
    b = db.create_studio_project("B")
    _add_clip(db, mid_a, a.id)
    _add_clip(db, mid_b, b.id)
    c.get(f"/studio?project_id={b.id}")
    cleared = c.post("/studio/clear", follow_redirects=False)
    assert cleared.status_code == 303
    assert db.list_studio_items(b.id) == []
    assert len(db.list_studio_items(a.id)) == 1
    assert db.get_studio_project(b.id) is not None
    assert db.get_media(mid_a) is not None
    assert db.get_media(mid_b) is not None


def test_export_options_without_open_project_is_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _db = _client(tmp_path, monkeypatch)
    opts = c.get("/api/studio/export/options")
    assert opts.status_code == 400

