"""Browse bulk Add to Studio: membership-safe batch insert + browse state."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.i18n import clear_catalog_cache


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    clear_catalog_cache()
    from orga_drone.app import create_app

    return create_app()


def _seed_many(db: Database, root: Path, count: int) -> list[int]:
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label="t")
    ids: list[int] = []
    for i in range(count):
        name = f"clip_{i:04d}.MP4"
        f = root / name
        f.write_bytes(b"x")
        mid = db.upsert_media(
            {
                "root_id": root_id,
                "primary_asset_id": None,
                "kind": "video",
                "filename": name,
                "path": str(f.resolve()),
                "size_bytes": 1000 + i,
                "duration_s": 1.0 + i,
                "recorded_at": f"2024-06-{(i % 28) + 1:02d}T12:00:00",
                "sequence": None,
                "mode": None,
                "drone_model": "Mini 4 Pro" if i % 2 == 0 else "Avata 2",
                "camera_model": None,
                "latitude": None,
                "longitude": None,
                "abs_alt": None,
                "has_srt": 0,
                "has_lrf": 0,
                "track_json": None,
            }
        )
        ids.append(mid)
    return ids


def _open_project(db: Database, client: TestClient):
    project = db.ensure_default_studio_project()
    db.set_open_studio_project_id(project.id)
    opened = client.get(f"/studio?project_id={project.id}", follow_redirects=False)
    assert opened.status_code in {200, 303}
    return project


def test_bulk_add_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    ids = _seed_many(db, tmp_path / "lib", 5)
    client = TestClient(app)
    project = _open_project(db, client)

    resp = client.post(
        "/studio/add-bulk",
        data={"return_to": "/browse", "media_ids": [str(ids[0]), str(ids[1]), str(ids[2])]},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    loc = resp.headers["location"]
    assert loc.startswith("/browse?")
    qs = parse_qs(urlparse(loc).query)
    assert qs.get("msg") == ["studio_bulk_added"]
    assert qs.get("added") == ["3"]
    assert qs.get("skipped") == ["0"]

    clips = db.list_studio_items(project.id)
    assert len(clips) == 3
    paths = {c.media_path for c in clips}
    assert db.get_media(ids[0]).path in paths
    assert db.get_media(ids[1]).path in paths
    assert db.get_media(ids[2]).path in paths


def test_bulk_add_skips_existing_without_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    ids = _seed_many(db, tmp_path / "lib", 4)
    client = TestClient(app)
    project = _open_project(db, client)

    a = db.get_media(ids[0])
    assert a is not None
    db.add_studio_item(
        a.path,
        identity_key=make_identity_key(a.filename, a.size_bytes, a.recorded_at),
        filename=a.filename,
        recorded_at=a.recorded_at,
        kind=a.kind,
        project_id=project.id,
        source_media_id=a.id,
    )
    assert len(db.list_studio_items(project.id)) == 1

    resp = client.post(
        "/studio/add-bulk",
        data={
            "return_to": "/browse",
            "media_ids": [str(ids[0]), str(ids[1]), str(ids[2])],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    assert qs.get("added") == ["2"]
    assert qs.get("skipped") == ["1"]

    clips = db.list_studio_items(project.id)
    assert len(clips) == 3
    assert sum(1 for c in clips if c.media_path == a.path) == 1


def test_bulk_add_preserves_browse_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    total = 210
    _seed_many(db, tmp_path / "lib", total)
    client = TestClient(app)
    _open_project(db, client)

    browse = client.get(
        "/browse",
        params={
            "kind": "video",
            "drone": "Avata 2",
            "page": 2,
            "page_size": 100,
            "view": "grid",
            "sort": "filename",
            "order": "asc",
        },
    )
    assert browse.status_code == 200
    html = browse.text
    assert 'id="browse-bulk-studio"' in html
    assert 'action="/studio/add-bulk"' in html
    assert 'name="return_to" value="/browse?' in html
    assert "page=2" in html
    assert "page_size=100" in html
    assert 'class="browse-select-input"' in html
    assert "Add selected to Studio" in html or "Auswahl zum Studio hinzufügen" in html

    # Extract return_to from bulk form and one selectable media id.
    form_idx = html.index('id="browse-bulk-studio"')
    form_chunk = html[form_idx : form_idx + 550]
    rt_prefix = 'name="return_to" value="'
    assert rt_prefix in form_chunk
    rt_start = form_chunk.index(rt_prefix) + len(rt_prefix)
    return_to = form_chunk[rt_start : form_chunk.index('"', rt_start)]
    assert return_to.startswith("/browse?")
    assert "page=2" in return_to
    assert "page_size=100" in return_to
    assert "kind=video" in return_to
    assert "sort=filename" in return_to

    import re

    match = re.search(
        r'name="media_ids" value="(\d+)"[^>]*form="browse-bulk-studio"(?![^>]*disabled)',
        html,
    )
    if match is None:
        match = re.search(
            r'form="browse-bulk-studio"[^>]*name="media_ids" value="(\d+)"(?![^>]*disabled)',
            html,
        )
    assert match is not None
    mid = match.group(1)

    add = client.post(
        "/studio/add-bulk",
        data={"return_to": return_to, "media_ids": [mid]},
        follow_redirects=False,
    )
    assert add.status_code == 303
    loc = add.headers["location"]
    assert "page=2" in loc
    assert "page_size=100" in loc
    assert "kind=video" in loc
    assert "sort=filename" in loc
    assert "msg=studio_bulk_added" in loc

    after = client.get(loc)
    assert after.status_code == 200
    assert "In Studio" in after.text or "Im Studio" in after.text
    assert f'value="{mid}"' in after.text


def test_bulk_add_empty_and_invalid_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    ids = _seed_many(db, tmp_path / "lib", 2)
    client = TestClient(app)
    project = _open_project(db, client)

    empty = client.post(
        "/studio/add-bulk",
        data={"return_to": "/browse?page=2&kind=video"},
        follow_redirects=False,
    )
    assert empty.status_code == 303
    assert empty.headers["location"] == "/browse?page=2&kind=video"
    assert db.list_studio_items(project.id) == []

    bad = client.post(
        "/studio/add-bulk",
        data={
            "return_to": "/browse?page=2",
            "media_ids": ["999999", "nope", str(ids[0])],
        },
        follow_redirects=False,
    )
    assert bad.status_code == 303
    qs = parse_qs(urlparse(bad.headers["location"]).query)
    assert qs.get("added") == ["1"]
    assert qs.get("page") == ["2"]
    assert len(db.list_studio_items(project.id)) == 1

    evil = client.post(
        "/studio/add-bulk",
        data={
            "return_to": "https://evil.example/",
            "media_ids": [str(ids[1])],
        },
        follow_redirects=False,
    )
    assert evil.status_code == 303
    assert evil.headers["location"].startswith("/browse?")


def test_bulk_add_needs_open_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    ids = _seed_many(db, tmp_path / "lib", 1)
    client = TestClient(app)
    # No open project (and clear any default open pointer).
    db.set_open_studio_project_id(None)
    for p in db.list_studio_projects():
        db.delete_studio_project(p.id)

    resp = client.post(
        "/studio/add-bulk",
        data={"return_to": "/browse", "media_ids": [str(ids[0])]},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/studio?msg=studio_need_project"


def test_list_view_renders_bulk_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    _seed_many(db, tmp_path / "lib", 3)
    client = TestClient(app)
    _open_project(db, client)
    page = client.get("/browse", params={"view": "list"})
    assert page.status_code == 200
    assert 'id="browse-bulk-studio"' in page.text
    assert "browse-select-col" in page.text
    assert 'form="browse-bulk-studio"' in page.text
