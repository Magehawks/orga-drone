"""HTTP routes for canonical grade wrap/publish/convert (#363)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.studio_grade_persistence import startup_backup_if_needed


@pytest.fixture()
def grade_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, int]:
    data_dir = tmp_path / "data"
    settings = Settings(data_dir=data_dir)
    monkeypatch.setattr("orga_drone.app.settings", settings)
    monkeypatch.setattr("orga_drone.config.settings", settings)
    db = Database(settings.db_path)
    startup_backup_if_needed(data_dir, app_version="test")
    root = tmp_path / "lib"
    root.mkdir()
    root_id = db.add_root(root, label="t")
    media = root / "a.jpg"
    media.write_bytes(b"x")
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": "a.jpg",
            "path": str(media.resolve()),
            "size_bytes": 1,
            "duration_s": None,
            "recorded_at": "2024-01-01T00:00:00",
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
    item = db.get_media(media_id)
    assert item is not None
    clip_id, _ = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
    )
    db.set_studio_image_adjust(clip_id, {"exposure": 15})
    from orga_drone.app import create_app

    return TestClient(create_app()), clip_id


def test_grade_wrap_get_and_convert(
    grade_client: tuple[TestClient, int],
) -> None:
    client, clip_id = grade_client
    got = client.get(f"/api/studio/{clip_id}/grade")
    assert got.status_code == 200
    assert got.json()["authority"] == "legacy"
    wrapped = client.post(f"/api/studio/{clip_id}/grade/wrap")
    assert wrapped.status_code == 200
    body = wrapped.json()
    assert body["authority"] == "canonical"
    assert body["evaluator"] == "legacy-v1"
    assert body["grade"]["steps"][0]["params"]["image"]["exposure"] == 15
    blocked = client.patch(f"/api/studio/{clip_id}/image", json={"exposure": 1})
    assert blocked.status_code == 409
    converted = client.post(
        f"/api/studio/{clip_id}/grade/convert-managed",
        json={"acknowledge_appearance_change": True},
    )
    assert converted.status_code == 200
    assert converted.json()["evaluator"] == "managed-sdr-v1"
    assert converted.json()["grade"]["steps"] == []


def test_grade_command_route_and_capabilities(
    grade_client: tuple[TestClient, int],
) -> None:
    client, clip_id = grade_client
    client.post(f"/api/studio/{clip_id}/grade/wrap")
    converted = client.post(
        f"/api/studio/{clip_id}/grade/convert-managed",
        json={"acknowledge_appearance_change": True},
    )
    assert converted.status_code == 200
    revision = int(converted.json()["revision"])
    grade = converted.json()["grade"]
    grade["steps"] = [
        {
            "id": "step-1",
            "type": "primaries-v1",
            "enabled": True,
            "mix": 1,
            "params": {"exposure": 0.0},
            "selection_id": None,
        }
    ]
    put = client.put(
        f"/api/studio/{clip_id}/grade",
        json={"grade": grade, "expected_revision": revision, "vendor_keep": {"x": 1}},
    )
    assert put.status_code == 200
    revision = int(put.json()["revision"])
    got = client.get(f"/api/studio/{clip_id}/grade")
    assert got.status_code == 200
    caps = got.json()["capabilities"]
    assert "set_step_mix" in caps["commands"]
    assert caps["writes"] is True
    assert "primaries-v1" in caps["operations"]
    cmd = client.post(
        f"/api/studio/{clip_id}/grade/command",
        json={
            "type": "set_step_mix",
            "expected_revision": revision,
            "params": {"step_id": "step-1", "mix": 0.4},
        },
    )
    assert cmd.status_code == 200
    body = cmd.json()
    assert body["grade"]["steps"][0]["mix"] == 0.4
    assert body["revision"] == revision + 1
    assert body["changed"] is True
    # Opaque root preserved through command publish.
    assert got.json()["grade"] is not None
    stale = client.post(
        f"/api/studio/{clip_id}/grade/command",
        json={
            "type": "set_step_enabled",
            "expected_revision": revision,
            "params": {"step_id": "step-1", "enabled": False},
        },
    )
    assert stale.status_code == 409
