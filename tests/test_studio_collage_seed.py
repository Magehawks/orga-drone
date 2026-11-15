"""Library selection seeds collage leaves without re-picking (#468)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.i18n import clear_catalog_cache
from orga_drone.studio_collage import collage_spec_from_raw, iter_leaves
from orga_drone.studio_collage_seed import (
    preset_for_count,
    seed_collage_from_media_ids,
)


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    clear_catalog_cache()
    from orga_drone.app import create_app

    return create_app()


def _seed_photos(db: Database, root: Path, count: int) -> list[int]:
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label="t")
    ids: list[int] = []
    for i in range(count):
        name = f"p{i}.jpg"
        path = root / name
        Image.new("RGB", (64, 48), (40 + i * 20, 80, 120)).save(path, format="JPEG")
        mid = db.upsert_media(
            {
                "root_id": root_id,
                "primary_asset_id": None,
                "kind": "photo",
                "filename": name,
                "path": str(path.resolve()),
                "size_bytes": path.stat().st_size,
                "duration_s": None,
                "recorded_at": f"2024-06-{(i % 28) + 1:02d}T12:00:00",
                "sequence": None,
                "mode": None,
                "drone_model": "Mini 4 Pro",
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


def test_preset_for_count_mapping() -> None:
    assert preset_for_count(1) == "1+1"
    assert preset_for_count(3) == "2+1"
    assert preset_for_count(4) == "2x2"
    assert preset_for_count(5) == "3|2"
    assert preset_for_count(8) == "3x2"


def test_seed_fills_leaves_and_appends_leftovers(tmp_path: Path) -> None:
    db = Database(tmp_path / "lib.sqlite3")
    ids = _seed_photos(db, tmp_path / "media", 8)
    project = db.create_studio_project("Seed")
    collage, assigned, leftovers = seed_collage_from_media_ids(db, project.id, ids)
    assert collage.item_kind == "collage"
    assert assigned == 6
    assert leftovers == 2
    spec = collage_spec_from_raw(collage.collage_spec)
    leaves = iter_leaves(spec["root"])
    assert len(leaves) == 6
    for leaf, mid in zip(leaves, ids[:6], strict=True):
        media = leaf.get("media") or {}
        assert media.get("source") == "library"
        assert media.get("media_id") == mid
    clips = [c for c in db.list_studio_items(project.id) if c.item_kind == "media"]
    assert len(clips) == 2


def test_bulk_add_seed_collage_opens_studio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    ids = _seed_photos(db, tmp_path / "lib", 3)
    client = TestClient(app)
    db.set_open_studio_project_id(None)
    for p in db.list_studio_projects():
        db.delete_studio_project(p.id)

    resp = client.post(
        "/studio/add-bulk",
        data={
            "return_to": "/browse",
            "media_ids": [str(i) for i in ids],
            "project_mode": "new",
            "project_title": "Collage set",
            "open_studio": "1",
            "seed": "collage",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    loc = resp.headers["location"]
    assert loc.startswith("/studio?")
    qs = parse_qs(urlparse(loc).query)
    assert qs.get("msg") == ["studio_bulk_added"]
    assert "select" in qs
    projects = db.list_studio_projects()
    assert len(projects) == 1
    items = db.list_studio_items(projects[0].id)
    collages = [i for i in items if i.item_kind == "collage"]
    assert len(collages) == 1
    assert int(qs["select"][0]) == collages[0].id
    leaves = iter_leaves(collage_spec_from_raw(collages[0].collage_spec)["root"])
    assert len(leaves) == 3
    assert all((leaf.get("media") or {}).get("media_id") for leaf in leaves)


def test_chooser_exposes_new_collage_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    _seed_photos(db, tmp_path / "lib", 1)
    client = TestClient(app)
    page = client.get("/browse")
    assert page.status_code == 200
    assert 'id="browse-studio-new-collage"' in page.text
    assert 'name="seed"' in page.text
    assert "New collage" in page.text or "Neue Collage" in page.text
