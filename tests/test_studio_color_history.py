"""Undo/Redo and project persistence for Studio color edits.

Story history is covered for structural edits in ``test_studio_history.py``;
this file proves the color setters (image adjust, HSL, wheels, look) join the
same session history and that their ``effect_settings`` survive a database
reopen. Issue #211 acceptance: "Undo/redo covers effect and keyframe edits".
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.studio_color_wheels import color_wheels_from_effect_settings
from orga_drone.studio_hsl import hsl_adjust_from_effect_settings
from orga_drone.studio_lut import color_look_from_effect_settings


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def _seed(db: Database, root: Path, filename: str) -> int:
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label=filename)
    media_file = root / filename
    media_file.write_bytes(b"media-bytes-" + filename.encode("ascii"))
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": filename,
            "path": str(media_file.resolve()),
            "size_bytes": media_file.stat().st_size,
            "duration_s": 12.0,
            "recorded_at": "2024-06-01T12:00:00",
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
    item = db.get_media(media_id)
    assert item is not None
    clip_id, _created = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
    )
    return clip_id


def _stored(db: Database, clip_id: int):
    items = {item.id: item for item in db.list_studio_items()}
    assert clip_id in items
    return items[clip_id]


def test_hsl_edit_undo_redo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed(db, tmp_path / "videos", "HSL.MP4")

    saved = client.patch(
        f"/api/studio/{clip_id}/hsl",
        json={"ranges": {"orange": {"hue": 10, "saturation": -80, "luminance": 20}}},
    )
    assert saved.status_code == 200
    assert hsl_adjust_from_effect_settings(
        _stored(db, clip_id).effect_settings
    ).orange.saturation == -80

    assert client.post("/api/studio/history/undo").status_code == 200
    assert hsl_adjust_from_effect_settings(_stored(db, clip_id).effect_settings).is_neutral

    assert client.post("/api/studio/history/redo").status_code == 200
    restored = hsl_adjust_from_effect_settings(_stored(db, clip_id).effect_settings)
    assert restored.orange.hue == 10
    assert restored.orange.saturation == -80
    assert restored.orange.luminance == 20


def test_wheels_edit_undo_redo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed(db, tmp_path / "videos", "WHEEL.MP4")

    saved = client.patch(
        f"/api/studio/{clip_id}/color-wheels",
        json={"wheels": {"shadows": {"x": 0.4, "y": -0.2}, "highlights": {"x": -0.3, "y": 0.3}}},
    )
    assert saved.status_code == 200
    stored_wheels = color_wheels_from_effect_settings(_stored(db, clip_id).effect_settings)
    assert (stored_wheels.shadows.x, stored_wheels.shadows.y) == pytest.approx((0.4, -0.2))

    assert client.post("/api/studio/history/undo").status_code == 200
    assert color_wheels_from_effect_settings(_stored(db, clip_id).effect_settings).is_neutral

    assert client.post("/api/studio/history/redo").status_code == 200
    restored = color_wheels_from_effect_settings(_stored(db, clip_id).effect_settings)
    assert (restored.highlights.x, restored.highlights.y) == pytest.approx((-0.3, 0.3))


def test_look_edit_undo_redo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed(db, tmp_path / "videos", "LOOK.MP4")
    cube = tmp_path / "identity.cube"
    from orga_drone.studio_lut import write_identity_cube

    write_identity_cube(cube)
    imported = client.post("/api/studio/luts", json={"path": str(cube)})
    assert imported.status_code == 200
    asset = imported.json()["asset_name"]

    saved = client.patch(
        f"/api/studio/{clip_id}/color",
        json={
            "input_profile": "dlog_m",
            "conversion_lut": asset,
            "conversion_confirmed": True,
            "creative_lut": asset,
            "creative_strength": 60,
        },
    )
    assert saved.status_code == 200
    stored_look = color_look_from_effect_settings(_stored(db, clip_id).effect_settings)
    assert stored_look.conversion_lut == asset
    assert stored_look.creative_strength == 60

    assert client.post("/api/studio/history/undo").status_code == 200
    assert color_look_from_effect_settings(_stored(db, clip_id).effect_settings).is_neutral

    assert client.post("/api/studio/history/redo").status_code == 200
    restored = color_look_from_effect_settings(_stored(db, clip_id).effect_settings)
    assert restored.conversion_confirmed is True
    assert restored.creative_lut == asset
    assert restored.creative_strength == 60


def test_color_slider_group_is_one_history_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed(db, tmp_path / "videos", "GROUP.MP4")
    group = {"X-Studio-History-Group": "hsl-mixer"}

    first = client.patch(
        f"/api/studio/{clip_id}/hsl",
        json={"ranges": {"blue": {"saturation": -40}}},
        headers=group,
    )
    second = client.patch(
        f"/api/studio/{clip_id}/hsl",
        json={"ranges": {"blue": {"saturation": -90}}},
        headers=group,
    )
    assert first.status_code == 200 and second.status_code == 200
    assert hsl_adjust_from_effect_settings(
        _stored(db, clip_id).effect_settings
    ).blue.saturation == -90

    assert client.post("/api/studio/history/undo").status_code == 200
    assert hsl_adjust_from_effect_settings(_stored(db, clip_id).effect_settings).is_neutral

    assert client.post("/api/studio/history/redo").status_code == 200
    assert (
        hsl_adjust_from_effect_settings(_stored(db, clip_id).effect_settings).blue.saturation
        == -90
    )


def test_color_edits_survive_database_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed(db, tmp_path / "videos", "REOPEN.MP4")
    assert client.patch(
        f"/api/studio/{clip_id}/hsl",
        json={"ranges": {"green": {"hue": -15, "saturation": 45, "luminance": -10}}},
    ).status_code == 200
    assert client.patch(
        f"/api/studio/{clip_id}/color-wheels",
        json={"wheels": {"midtones": {"x": 0.25, "y": -0.25}}},
    ).status_code == 200

    reopened = Database(db.path)
    stored = {item.id: item for item in reopened.list_studio_items()}[clip_id]
    hsl = hsl_adjust_from_effect_settings(stored.effect_settings)
    wheels = color_wheels_from_effect_settings(stored.effect_settings)
    assert (hsl.green.hue, hsl.green.saturation, hsl.green.luminance) == (-15, 45, -10)
    assert (wheels.midtones.x, wheels.midtones.y) == pytest.approx((0.25, -0.25))
