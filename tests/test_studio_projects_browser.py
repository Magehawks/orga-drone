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

    page = c.get("/studio/projects")
    assert page.status_code == 200
    assert "Keep" in page.text
    assert "Doomed" not in page.text


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

    page = c.get("/studio", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"] == "/studio/projects"
    gallery = c.get("/studio/projects")
    assert gallery.status_code == 200
    assert "No Studio projects yet" in gallery.text or "Noch keine Studio-Projekte" in gallery.text
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
    assert 'id="studio-projects-back"' in page.text
    assert 'href="/studio/projects"' in page.text
    after_creator = page.text.split('class="studio-creator"', 1)[1]
    assert 'id="studio-projects-dialog"' not in after_creator
    title_cluster = after_creator.split("studio-topbar-title", 1)[1].split(
        "studio-topbar-actions", 1
    )[0]
    assert 'id="studio-projects-back"' in title_cluster
    assert 'id="studio-project-title"' in title_cluster
    assert "studio-project-identity-label" in title_cluster
    actions = after_creator.split("studio-topbar-actions", 1)[1].split(
        "</div>", 1
    )[0]
    assert 'id="studio-export-open"' in actions
    assert "studio-clear-form" not in actions
    assert 'id="studio-projects-back"' not in actions
    toolbar = after_creator.split("studio-timeline-toolbar", 1)[1].split(
        "studio-timeline-row", 1
    )[0]
    assert "studio-clear-form" in toolbar
    assert "Clear Studio" in toolbar or "Studio leeren" in toolbar
    assert "Remove all clips from this Story" in after_creator or (
        "Alle Clips aus dieser Story" in after_creator
    )
    assert "Back to projects" in after_creator or "Zurück zu Projekten" in after_creator
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


def test_project_lists_scroll_inside_a_short_window() -> None:
    """Many projects stay reachable when the Studio window is shorter than the list.

    The landing and the Projects dialog are the scroll containers. Their rows
    are buttons, so Tab moves through them and the browser scrolls the focused
    row into view. The dialog also keeps a max-height so Close stays in the window.
    """
    css = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "orga_drone"
        / "static"
        / "css"
        / "app.css"
    ).read_text(encoding="utf-8")
    landing = css.split(".studio-project-landing {", 1)[1].split("}", 1)[0]
    assert "min-height: 0" in landing
    assert "overflow: auto" in landing
    dialog = css.split(".studio-projects-dialog {", 1)[1].split("}", 1)[0]
    assert "max-height: calc(100vh - 2rem)" in dialog
    assert "overflow: auto" in dialog
    project_list = css.split(".studio-projects-dialog .studio-project-list {", 1)[1].split(
        "}", 1
    )[0]
    assert "overflow: auto" in project_list
    assert "calc(100vh - 14rem)" in project_list


def test_gallery_create_does_not_reuse_the_open_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, db = _client(tmp_path, monkeypatch)
    mid = _seed_media(db, tmp_path / "lib")
    older = db.create_studio_project("Older film")
    _add_clip(db, mid, older.id)
    db.set_open_studio_project_id(older.id)

    created = c.post("/studio/projects", follow_redirects=False)
    assert created.status_code == 303
    assert created.headers["location"] == "/studio"
    editor = c.get("/studio")
    assert editor.status_code == 200
    assert 'data-studio-mode="editor"' in editor.text
    opened = db.get_open_studio_project()
    assert opened is not None
    assert opened.id != older.id
    assert db.list_studio_items(opened.id) == []
    assert len(db.list_studio_items(older.id)) == 1
    gallery = c.get("/studio/projects")
    assert "Older film" in gallery.text
    assert opened.title in gallery.text


def test_gallery_opens_the_saved_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, db = _client(tmp_path, monkeypatch)
    mid = _seed_media(db, tmp_path / "lib")
    project = db.create_studio_project("Saved flight")
    clip_id = _add_clip(db, mid, project.id)
    with db.connect() as conn:
        conn.execute(
            "UPDATE studio_clips SET source_start = ?, effect_settings = ? WHERE id = ?",
            (1.25, '{"brightness": 1.1}', clip_id),
        )
    gallery = c.get("/studio/projects")
    assert gallery.status_code == 200
    assert f'href="/studio?project_id={project.id}"' in gallery.text
    opened = c.get(f"/studio?project_id={project.id}", follow_redirects=False)
    assert opened.status_code == 303
    assert opened.headers["location"] == "/studio"
    editor = c.get("/studio")
    assert "Saved flight" in editor.text
    saved = db.list_studio_items(project.id)
    assert len(saved) == 1
    assert saved[0].source_start == 1.25
    assert saved[0].effect_settings == '{"brightness": 1.1}'


def test_gallery_lists_fifty_projects_without_the_locked_studio_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, db = _client(tmp_path, monkeypatch)
    created = [
        db.create_studio_project(f"Story {index:02d}") for index in range(50)
    ]
    with db.connect() as conn:
        for index, project in enumerate(created):
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (f"2024-01-01T00:00:{index:02d}", project.id),
            )
    page = c.get("/studio/projects")
    assert page.status_code == 200
    body = page.text.split("<body", 1)[1].split(">", 1)[0]
    assert "studio-app" not in body
    for index in range(50):
        assert f"Story {index:02d}" in page.text
    assert page.text.index("Story 49") < page.text.index("Story 00")


def test_gallery_search_markup_and_languages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, db = _client(tmp_path, monkeypatch)
    db.create_studio_project("Harbor")
    english = c.get("/studio/projects", cookies={"lang": "en", "theme": "light"})
    assert 'data-theme="light"' in english.text
    assert 'id="studio-gallery-search"' in english.text
    assert 'data-project-title="Harbor"' in english.text
    assert "Search projects" in english.text
    german = c.get("/studio/projects", cookies={"lang": "de", "theme": "custom"})
    assert 'data-theme="custom"' in german.text
    assert "Projekte suchen" in german.text
    assert "Neues Projekt" in german.text
    editor = c.get("/studio", cookies={"lang": "en"})
    assert "Back to projects" in editor.text


def test_gallery_uses_a_cached_thumb_and_survives_a_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, db = _client(tmp_path, monkeypatch)
    present = _seed_media(db, tmp_path / "lib", filename="DJI_0001.MP4")
    missing = _seed_media(db, tmp_path / "lib", filename="DJI_0002.MP4")
    with_thumb = db.create_studio_project("With thumb")
    offline = db.create_studio_project("Offline")
    _add_clip(db, present, with_thumb.id)
    _add_clip(db, missing, offline.id)
    (tmp_path / "data" / "thumbs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "thumbs" / f"{present}_cached.jpg").write_bytes(b"jpeg")
    missing_item = db.get_media(missing)
    assert missing_item is not None
    Path(missing_item.path).unlink()

    page = c.get("/studio/projects")
    assert page.status_code == 200
    assert f"/media/{present}/cached-thumb" in page.text
    assert f"/media/{missing}/cached-thumb" not in page.text
    assert "studio-gallery-logo" in page.text
    assert 'loading="lazy"' in page.text


def test_export_options_without_open_project_is_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _db = _client(tmp_path, monkeypatch)
    opts = c.get("/api/studio/export/options")
    assert opts.status_code == 400

