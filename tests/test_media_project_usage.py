"""Media details: Studio projects that reference a library media file (#445)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key, remember_studio_original
from orga_drone.i18n import clear_catalog_cache


def _seed_media(
    db: Database,
    root_path: Path,
    *,
    filename: str,
    content: bytes = b"fake",
    kind: str = "video",
) -> int:
    root_path.mkdir(parents=True, exist_ok=True)
    roots = db.list_roots()
    root_id = roots[0]["id"] if roots else db.add_root(root_path, label="lib")
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
            "duration_s": 12.0 if kind == "video" else None,
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


def test_studio_projects_for_media_empty(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(db, tmp_path / "lib", filename="alone.MP4")
    assert db.studio_projects_for_media(mid) == []
    assert db.studio_projects_for_media(999_999) == []


def test_studio_projects_for_media_dedupes_and_counts(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(db, tmp_path / "lib", filename="clip.MP4", content=b"aaaa")
    other = _seed_media(db, tmp_path / "lib", filename="other.MP4", content=b"bbbb")
    infinity = db.create_studio_project("Infinity")
    hubland = db.create_studio_project("Hubland")
    unused = db.create_studio_project("Unused")
    _add_clip(db, mid, infinity.id)
    _add_clip(db, mid, infinity.id)
    _add_clip(db, mid, hubland.id)
    _add_clip(db, other, unused.id)

    usage = db.studio_projects_for_media(mid)
    assert [u.title for u in usage] == ["Hubland", "Infinity"]
    assert usage[0].clip_count == 1
    assert usage[1].clip_count == 2
    assert unused.id not in {u.id for u in usage}


def test_studio_projects_for_media_ignores_identical_filenames(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "t.sqlite3")
    a = _seed_media(db, tmp_path / "a", filename="DJI_0001.MP4", content=b"aaaa")
    b = _seed_media(db, tmp_path / "b", filename="DJI_0001.MP4", content=b"bbbb")
    project = db.create_studio_project("Only A")
    _add_clip(db, a, project.id)

    assert [u.id for u in db.studio_projects_for_media(a)] == [project.id]
    assert db.studio_projects_for_media(b) == []


def test_studio_projects_for_media_skips_deleted_projects(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(db, tmp_path / "lib", filename="gone.MP4")
    project = db.create_studio_project("Temp")
    _add_clip(db, mid, project.id)
    assert len(db.studio_projects_for_media(mid)) == 1
    assert db.delete_studio_project(project.id) is True
    assert db.studio_projects_for_media(mid) == []


def test_studio_projects_for_media_path_match_without_source_id(
    tmp_path: Path,
) -> None:
    """Legacy / orphaned source_media_id still matches via canonical path."""
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(db, tmp_path / "lib", filename="legacy.MP4")
    project = db.create_studio_project("Legacy")
    clip_id = _add_clip(db, mid, project.id)
    with db.connect() as conn:
        conn.execute(
            "UPDATE studio_clips SET source_media_id = NULL WHERE id = ?",
            (clip_id,),
        )
    usage = db.studio_projects_for_media(mid)
    assert len(usage) == 1
    assert usage[0].id == project.id
    assert usage[0].clip_count == 1


def test_studio_projects_for_media_source_id_when_path_stale(
    tmp_path: Path,
) -> None:
    """Moved/unavailable path still matches when source_media_id is intact."""
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(db, tmp_path / "lib", filename="moved.MP4")
    project = db.create_studio_project("Moved")
    clip_id = _add_clip(db, mid, project.id)
    with db.connect() as conn:
        conn.execute(
            "UPDATE studio_clips SET media_path = ? WHERE id = ?",
            (str(tmp_path / "missing" / "moved.MP4"), clip_id),
        )
    usage = db.studio_projects_for_media(mid)
    assert len(usage) == 1
    assert usage[0].id == project.id


def test_studio_projects_for_media_prefers_id_over_conflicting_path(
    tmp_path: Path,
) -> None:
    """Explicit source_media_id wins; a path that matches another file must not."""
    db = Database(tmp_path / "t.sqlite3")
    media_a = _seed_media(db, tmp_path / "a", filename="A.MP4", content=b"aaaa")
    media_b = _seed_media(db, tmp_path / "b", filename="B.MP4", content=b"bbbb")
    item_b = db.get_media(media_b)
    assert item_b is not None
    project = db.create_studio_project("Owned by A")
    clip_id = _add_clip(db, media_a, project.id)
    with db.connect() as conn:
        conn.execute(
            "UPDATE studio_clips SET media_path = ? WHERE id = ?",
            (item_b.path, clip_id),
        )

    usage_a = db.studio_projects_for_media(media_a)
    assert [u.id for u in usage_a] == [project.id]
    assert usage_a[0].clip_count == 1

    # Path equals B, but source_media_id still points at A → B is unused.
    assert db.studio_projects_for_media(media_b) == []


def test_studio_projects_for_media_includes_original_without_clips(
    tmp_path: Path,
) -> None:
    """studio_originals can keep membership after Story clips are removed."""
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(db, tmp_path / "lib", filename="kept.MP4", content=b"keep")
    item = db.get_media(mid)
    assert item is not None
    project = db.create_studio_project("Original only")
    clip_id = _add_clip(db, mid, project.id)
    with db.connect() as conn:
        remember_studio_original(
            conn,
            project_id=project.id,
            media_path=item.path,
            source_media_id=mid,
            filename=item.filename,
            now="2024-01-02T10:00:00",
        )
        conn.execute("DELETE FROM studio_clips WHERE id = ?", (clip_id,))

    assert db.list_studio_items(project.id) == []
    assert db.list_studio_originals(project.id)[0]["media_id"] == mid
    usage = db.studio_projects_for_media(mid)
    assert len(usage) == 1
    assert usage[0].id == project.id
    assert usage[0].clip_count == 0
    assert usage[0].has_original is True


def test_studio_projects_for_media_renamed_project_title(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(db, tmp_path / "lib", filename="rename.MP4")
    project = db.create_studio_project("Old name")
    _add_clip(db, mid, project.id)
    db.set_studio_project_title(project.id, "New name")
    usage = db.studio_projects_for_media(mid)
    assert len(usage) == 1
    assert usage[0].title == "New name"


def test_detail_page_shows_project_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_catalog_cache()
    client, db = _client(tmp_path, monkeypatch)
    mid = _seed_media(db, tmp_path / "lib", filename="detail.MP4", content=b"dddd")
    infinity = db.create_studio_project("Infinity")
    hubland = db.create_studio_project("Hubland")
    _add_clip(db, mid, infinity.id)
    _add_clip(db, mid, infinity.id)
    _add_clip(db, mid, hubland.id)

    page = client.get(f"/media/{mid}", cookies={"lang": "en"})
    assert page.status_code == 200
    text = page.text
    assert 'id="detail-project-usage"' in text
    assert "Used in Projects" in text
    assert "Used in 2 projects" in text
    assert ">Infinity<" in text
    assert ">Hubland<" in text
    assert f'href="/studio?project_id={infinity.id}"' in text
    assert f'href="/studio?project_id={hubland.id}"' in text
    assert "×2" in text

    empty = _seed_media(db, tmp_path / "lib", filename="empty.MP4", content=b"eeee")
    empty_page = client.get(f"/media/{empty}", cookies={"lang": "en"})
    assert empty_page.status_code == 200
    assert "Not used in any project." in empty_page.text
    assert "Used in 2 projects" not in empty_page.text

    de_page = client.get(f"/media/{mid}", cookies={"lang": "de"})
    assert de_page.status_code == 200
    assert "Verwendet in Projekten" in de_page.text
    assert "Verwendet in 2 Projekten" in de_page.text

    de_empty = client.get(f"/media/{empty}", cookies={"lang": "de"})
    assert de_empty.status_code == 200
    assert "In keinem Projekt verwendet." in de_empty.text


def test_detail_page_shows_original_only_membership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_catalog_cache()
    client, db = _client(tmp_path, monkeypatch)
    mid = _seed_media(db, tmp_path / "lib", filename="orig.MP4", content=b"oooo")
    item = db.get_media(mid)
    assert item is not None
    project = db.create_studio_project("Kept original")
    with db.connect() as conn:
        remember_studio_original(
            conn,
            project_id=project.id,
            media_path=item.path,
            source_media_id=mid,
            filename=item.filename,
            now="2024-01-02T10:00:00",
        )

    page = client.get(f"/media/{mid}", cookies={"lang": "en"})
    assert page.status_code == 200
    assert "Used in 1 project" in page.text
    assert ">Kept original<" in page.text
    assert "Full recording" in page.text
    assert f'href="/studio?project_id={project.id}"' in page.text
    usage = db.studio_projects_for_media(mid)
    assert usage[0].clip_count == 0
    assert usage[0].has_original is True


def test_studio_project_open_from_detail_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    mid = _seed_media(db, tmp_path / "lib", filename="nav.MP4")
    project = db.create_studio_project("Navigate me")
    _add_clip(db, mid, project.id)

    page = client.get(f"/media/{mid}")
    assert f'href="/studio?project_id={project.id}"' in page.text

    opened = client.get(f"/studio?project_id={project.id}", follow_redirects=False)
    assert opened.status_code == 303
    assert opened.headers["location"] in {"/studio", "/studio?"}
    assert db.get_open_studio_project() is not None
    assert db.get_open_studio_project().id == project.id
