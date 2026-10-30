"""Central local LUT catalog (import, dedup, rename, safe delete)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.lut_library import (
    LutInUseError,
    delete_lut,
    import_lut_bytes,
    import_lut_path,
    list_catalog,
    rename_lut,
    sanitize_display_name,
    unique_display_name,
)
from orga_drone.studio_lut import write_identity_cube


def _db(tmp_path: Path) -> Database:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    return Database(data / "test.sqlite3")


def _seed_media(db: Database, root: Path, *, name: str = "V.MP4") -> int:
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label="t")
    path = root / name
    path.write_bytes(b"media")
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": name,
            "path": str(path.resolve()),
            "size_bytes": 5,
            "duration_s": 4.0,
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


def test_sanitize_and_unique_display_names(tmp_path: Path) -> None:
    db = _db(tmp_path)
    assert sanitize_display_name(r"C:\Looks\Warm Sunset.cube") == "Warm Sunset"
    assert sanitize_display_name("  ") == ""
    first = import_lut_path(db, tmp_path / "data", write_identity_cube(tmp_path / "a.cube"))
    assert unique_display_name(db, first.entry.display_name).endswith("(2)")


def test_import_dedup_and_restore(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    db = _db(tmp_path)
    cube = write_identity_cube(tmp_path / "look.cube")
    first = import_lut_path(db, data_dir, cube)
    assert first.already_present is False
    assert first.entry.asset_name.endswith(".cube")
    second = import_lut_path(db, data_dir, cube)
    assert second.already_present is True
    assert second.entry.asset_name == first.entry.asset_name
    path = data_dir / "luts" / first.entry.asset_name
    path.unlink()
    restored = import_lut_path(db, data_dir, cube)
    assert restored.restored is True
    assert restored.entry.asset_name == first.entry.asset_name
    assert path.is_file()


def test_rename_keeps_asset_name_and_blocks_collision(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    db = _db(tmp_path)
    one = import_lut_bytes(
        db, data_dir, write_identity_cube(tmp_path / "one.cube").read_bytes(), source_label="One.cube"
    )
    two_path = write_identity_cube(tmp_path / "two.cube", size=3)
    two = import_lut_path(db, data_dir, two_path)
    renamed = rename_lut(db, data_dir, one.entry.asset_name, "Golden Hour")
    assert renamed.asset_name == one.entry.asset_name
    assert renamed.display_name == "Golden Hour"
    with pytest.raises(ValueError, match="already exists"):
        rename_lut(db, data_dir, two.entry.asset_name, "Golden Hour")


def test_delete_blocked_when_in_use(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    db = _db(tmp_path)
    cube = write_identity_cube(tmp_path / "creative.cube")
    imported = import_lut_path(db, data_dir, cube)
    media_id = _seed_media(db, tmp_path / "lib")
    item = db.get_media(media_id)
    assert item is not None
    clip_id, _ = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
    )
    db.set_studio_color_look(
        clip_id,
        {
            "input_profile": "rec709",
            "conversion_lut": "",
            "creative_lut": imported.entry.asset_name,
            "creative_strength": 100,
            "conversion_confirmed": False,
        },
    )
    with pytest.raises(LutInUseError) as raised:
        delete_lut(db, data_dir, imported.entry.asset_name)
    assert raised.value.usage.clip_count == 1
    assert (data_dir / "luts" / imported.entry.asset_name).is_file()
    db.set_studio_color_look(
        clip_id,
        {
            "input_profile": "rec709",
            "conversion_lut": "",
            "creative_lut": "",
            "creative_strength": 100,
            "conversion_confirmed": False,
        },
    )
    delete_lut(db, data_dir, imported.entry.asset_name)
    assert db.get_lut_asset(imported.entry.asset_name) is None
    assert not (data_dir / "luts" / imported.entry.asset_name).is_file()


def test_legacy_file_gets_catalog_row(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    db = _db(tmp_path)
    luts = data_dir / "luts"
    luts.mkdir(parents=True)
    asset = "a" * 32 + ".cube"
    write_identity_cube(luts / asset)
    entries = list_catalog(db, data_dir)
    assert any(item.asset_name == asset for item in entries)
    row = db.get_lut_asset(asset)
    assert row is not None
    assert row.display_name


def test_http_luts_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    client = TestClient(app)
    cube = write_identity_cube(tmp_path / "http.cube")
    created = client.post("/api/luts", json={"path": str(cube)})
    assert created.status_code == 200
    body = created.json()
    assert body["ok"] is True
    assert body["asset_name"]
    asset = body["asset_name"]
    listed = client.get("/api/luts")
    assert listed.status_code == 200
    assert any(item["asset_name"] == asset for item in listed.json()["luts"])
    alias = client.post("/api/studio/luts", json={"path": str(cube)})
    assert alias.status_code == 200
    assert alias.json()["already_present"] is True
    renamed = client.patch(f"/api/luts/{asset}", json={"display_name": "Studio Look"})
    assert renamed.status_code == 200
    assert renamed.json()["display_name"] == "Studio Look"
    settings_page = client.get("/settings")
    assert settings_page.status_code == 200
    assert 'id="settings-luts"' in settings_page.text
    studio = client.get("/studio")
    assert studio.status_code in {200, 303}
    deleted = client.delete(f"/api/luts/{asset}")
    assert deleted.status_code == 200
