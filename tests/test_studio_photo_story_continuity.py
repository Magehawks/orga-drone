"""Adaptive Studio PR3 (#501): photo grades survive Story growth."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.studio_grade_persistence import startup_backup_if_needed
from tests.test_studio_clip_still import _put_managed, _spatial_grade


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    prefs = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr("orga_drone.app_prefs.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_export.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_clip_still.settings", prefs)
    monkeypatch.setattr("orga_drone.config.settings", prefs)
    monkeypatch.setattr("orga_drone.app.settings", prefs)
    startup_backup_if_needed(tmp_path / "data", app_version="continuity")
    return prefs


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    _isolate(monkeypatch, tmp_path)
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def _seed_photo(db: Database, root: Path, name: str, color: tuple[int, int, int]) -> int:
    root.mkdir(parents=True, exist_ok=True)
    photo = root / name
    Image.new("RGB", (32, 24), color).save(photo, format="JPEG", quality=90)
    root_id = db.add_root(root, label="continuity")
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": photo.name,
            "path": str(photo.resolve()),
            "size_bytes": photo.stat().st_size,
            "duration_s": None,
            "recorded_at": "2024-06-01T12:00:00",
            "sequence": 1,
            "mode": None,
            "drone_model": None,
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
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
        project_id=project_id,
        source_media_id=media_id,
    )
    return clip_id


def test_adding_second_clip_preserves_photo_managed_grade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    project = db.create_studio_project("Continuity")
    first_mid = _seed_photo(db, tmp_path / "lib", "first.jpg", (200, 40, 40))
    first_clip = _add_clip(db, first_mid, project.id)
    _put_managed(client, first_clip, _spatial_grade(invert=True, feather=0.08))

    before = client.get(f"/api/studio/{first_clip}/grade").json()
    assert before["evaluator"] == "managed-sdr-v1"
    before_blob = next(
        item.effect_settings
        for item in db.list_studio_items(project.id)
        if item.id == first_clip
    )

    second_mid = _seed_photo(db, tmp_path / "lib", "second.jpg", (40, 40, 200))
    second_clip = _add_clip(db, second_mid, project.id)
    assert second_clip != first_clip

    after = client.get(f"/api/studio/{first_clip}/grade").json()
    after_blob = next(
        item.effect_settings
        for item in db.list_studio_items(project.id)
        if item.id == first_clip
    )
    assert after["evaluator"] == "managed-sdr-v1"
    assert after["revision"] == before["revision"]
    assert after["grade"]["selections"] == before["grade"]["selections"]
    assert after_blob == before_blob
    stored = json.loads(after_blob)
    assert "managed-sdr-v1" in json.dumps(stored)
    assert after["grade"]["selections"][0]["invert"] is True

    clips = db.list_studio_items(project.id)
    assert [c.id for c in clips] == [first_clip, second_clip]
    second = next(c for c in clips if c.id == second_clip)
    assert second.effect_settings in ("{}", "")


def test_studio_page_exposes_continuity_hint_markup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    project = db.create_studio_project("Hint")
    mid = _seed_photo(db, tmp_path / "lib", "one.jpg", (10, 10, 10))
    _add_clip(db, mid, project.id)
    page = client.get("/studio")
    assert page.status_code == 200
    assert 'id="studio-context-continuity-hint"' in page.text
    assert 'id="studio-context-photo"' in page.text
    assert 'id="studio-context-story"' in page.text
