"""Studio project / clip model (Issue #16)."""

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


def test_same_media_can_be_referenced_multiple_times(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(
        db,
        tmp_path / "lib",
        filename="P.JPG",
        content=b"photo",
        kind="photo",
        duration_s=None,
    )
    item = db.get_media(mid)
    assert item is not None
    path = Path(item.path)
    before = path.read_bytes()

    id1, c1 = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
        source_media_id=mid,
    )
    id2, c2 = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
        source_media_id=mid,
    )
    assert c1 and c2
    assert id1 != id2
    clips = db.list_studio_items()
    assert len(clips) == 2
    assert clips[0].source_media_id == clips[1].source_media_id == mid
    assert clips[0].media_path == clips[1].media_path
    assert path.read_bytes() == before
    assert db.get_media(mid) is not None


def test_default_project_created_and_title_persists(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    project = db.ensure_default_studio_project()
    assert project.title == "Your story"
    again = db.ensure_default_studio_project()
    assert again.id == project.id

    updated = db.set_studio_project_title(project.id, "Alpine flight")
    assert updated.title == "Alpine flight"
    reopened = Database(tmp_path / "t.sqlite3")
    loaded = reopened.get_studio_project(project.id)
    assert loaded is not None
    assert loaded.title == "Alpine flight"


def test_clips_reference_media_without_copy(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(db, tmp_path / "lib", content=b"original-bytes")
    item = db.get_media(mid)
    assert item is not None
    path = Path(item.path)
    before = path.read_bytes()

    clip_id, created = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
        source_media_id=mid,
    )
    assert created is True
    clips = db.list_studio_items()
    assert len(clips) == 1
    clip = clips[0]
    assert clip.id == clip_id
    assert clip.source_media_id == mid
    assert clip.playback_speed == 1.0
    assert clip.volume == 1.0
    assert clip.effect_settings == "{}"
    assert path.read_bytes() == before

    left, right = db.cut_studio_video_item(clip_id, 4.0)
    assert left.source_media_id == mid
    assert right.source_media_id == mid
    assert left.media_path == right.media_path == item.path
    assert path.read_bytes() == before
    assert len(db.list_studio_items()) == 2


def test_delete_project_and_clip_never_deletes_media(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(db, tmp_path / "lib")
    item = db.get_media(mid)
    assert item is not None
    path = Path(item.path)
    assert path.is_file()

    project = db.create_studio_project("Temp edit")
    clip_id, _ = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
        project_id=project.id,
        source_media_id=mid,
    )
    assert db.remove_studio_item(clip_id) is True
    assert db.get_media(mid) is not None
    assert path.is_file()

    clip_id2, _ = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
        project_id=project.id,
        source_media_id=mid,
    )
    assert clip_id2 > 0
    assert db.delete_studio_project(project.id) is True
    assert db.get_studio_project(project.id) is None
    assert db.list_studio_items(project.id) == []
    assert db.get_media(mid) is not None
    assert path.is_file()


def test_http_project_title_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    project = db.ensure_default_studio_project()
    c = TestClient(app)

    page = c.get("/studio")
    assert page.status_code == 200
    assert f'data-project-id="{project.id}"' in page.text
    assert 'id="studio-project-title"' in page.text
    assert project.title in page.text

    bad = c.patch(f"/api/studio/projects/{project.id}", json={"title": "   "})
    assert bad.status_code == 400

    ok = c.patch(
        f"/api/studio/projects/{project.id}",
        json={"title": "Summer Alps 2026"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["ok"] is True
    assert body["title"] == "Summer Alps 2026"

    page2 = c.get("/studio")
    assert "Summer Alps 2026" in page2.text
    assert db.get_studio_project(project.id).title == "Summer Alps 2026"

    created = c.post("/api/studio/projects", json={"title": "Second"})
    assert created.status_code == 201
    second_id = created.json()["id"]
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
        project_id=second_id,
        source_media_id=mid,
    )
    media_count_before = len(db.list_media())
    deleted = c.delete(f"/api/studio/projects/{second_id}")
    assert deleted.status_code == 200
    assert len(db.list_media()) == media_count_before
    assert db.get_media(mid) is not None
