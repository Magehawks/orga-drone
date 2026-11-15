"""Empty-project Studio start panel (Normal / Collage / Skip) — #467."""

from __future__ import annotations

from pathlib import Path

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


def _seed_media(db: Database, root: Path) -> int:
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label="t")
    f = root / "clip.MP4"
    f.write_bytes(b"x")
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": "clip.MP4",
            "path": str(f.resolve()),
            "size_bytes": 1,
            "duration_s": 2.0,
            "recorded_at": "2024-06-01T12:00:00",
            "sequence": None,
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


def test_empty_project_shows_start_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    project = db.create_studio_project("Fresh")
    db.set_open_studio_project_id(project.id)
    client = TestClient(app)

    page = client.get(f"/studio?project_id={project.id}", follow_redirects=True)
    assert page.status_code == 200
    html = page.text
    assert 'id="studio-empty-start"' in html
    assert 'id="studio-empty-edit-normal"' in html
    assert 'id="studio-empty-create-collage"' in html
    assert 'id="studio-empty-skip"' in html
    assert 'id="studio-empty-hints"' in html
    assert "How do you want to start?" in html or "Wie möchtest du starten?" in html
    assert "Edit normally" in html or "Normal bearbeiten" in html
    assert "Create collage" in html or "Collage erstellen" in html


def test_non_empty_project_hides_start_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    project = db.create_studio_project("Busy")
    mid = _seed_media(db, tmp_path / "lib")
    media = db.get_media(mid)
    assert media is not None
    db.add_studio_item(
        media.path,
        identity_key=make_identity_key(
            media.filename, media.size_bytes, media.recorded_at
        ),
        filename=media.filename,
        recorded_at=media.recorded_at,
        kind=media.kind,
        project_id=project.id,
        source_media_id=media.id,
    )
    db.set_open_studio_project_id(project.id)
    client = TestClient(app)

    page = client.get(f"/studio?project_id={project.id}", follow_redirects=True)
    assert page.status_code == 200
    assert 'id="studio-empty-start"' not in page.text
    assert 'id="studio-empty-create-collage"' not in page.text


def test_create_collage_from_empty_project_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    project = db.create_studio_project("Collage start")
    db.set_open_studio_project_id(project.id)
    client = TestClient(app)
    client.get(f"/studio?project_id={project.id}")

    resp = client.post(
        "/api/studio/collages",
        json={"preset": "1+1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert data.get("id")
    items = db.list_studio_items(project.id)
    assert len(items) == 1
    assert items[0].item_kind == "collage"

    page = client.get(f"/studio?select={data['id']}", follow_redirects=True)
    assert page.status_code == 200
    assert 'id="studio-empty-start"' not in page.text
