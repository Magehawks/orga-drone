"""Photo Detail color persistence, undo, and still-export stack (#491)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image

from orga_drone.db import Database
from orga_drone.export.still_export import PRESET_BEST, export_photo_file
from orga_drone.photo_color import (
    clear_photo_color_history,
    effect_settings_from_photo_raw,
    merge_photo_hsl,
    merge_photo_image_adjust,
    photo_color_history_flags,
    photo_color_is_active,
    photo_color_needs_server_preview,
    photo_color_parts,
    redo_photo_color,
    undo_photo_color,
)
from orga_drone.studio_hsl import HslAdjust, HslRange
from orga_drone.studio_image import ImageAdjust


@pytest.fixture(autouse=True)
def _clear_history():
    clear_photo_color_history()
    yield
    clear_photo_color_history()


def _rgb_jpeg(path: Path, color=(40, 80, 160), size=(64, 48)) -> Path:
    Image.new("RGB", size, color).save(path, format="JPEG", quality=95)
    return path


def test_merge_preserves_hsl_when_basic_adjust_updates():
    hsl = HslAdjust(blue=HslRange(hue=20, saturation=10, luminance=-5))
    raw = merge_photo_hsl(None, hsl)
    raw2 = merge_photo_image_adjust(raw, ImageAdjust(exposure=12), look_id="")
    parts = photo_color_parts(raw2)
    assert parts.image.exposure == 12
    assert parts.hsl.blue.hue == 20
    assert photo_color_needs_server_preview(raw2)
    assert photo_color_is_active(raw2)


def test_effect_settings_view_nests_image():
    raw = merge_photo_image_adjust(None, ImageAdjust(contrast=8), look_id="vibrant")
    effect = effect_settings_from_photo_raw(raw)
    assert '"image"' in effect
    assert '"look"' in effect
    parts = photo_color_parts(raw)
    assert parts.look_id == "vibrant"


def test_photo_color_undo_redo_roundtrip(tmp_path: Path):
    db = Database(tmp_path / "lib.db")
    root = tmp_path / "lib"
    root.mkdir()
    root_id = db.add_root(root, label="lib")
    media = root / "a.jpg"
    _rgb_jpeg(media)
    db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": media.name,
            "path": str(media.resolve()),
            "size_bytes": media.stat().st_size,
            "duration_s": None,
            "recorded_at": "2024-01-01T00:00:00",
            "sequence": None,
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
    path = str(media.resolve())
    db.set_image_adjust(path, ImageAdjust(exposure=5), look_id="")
    first = db.get_image_adjust_json(path)
    hsl = HslAdjust(red=HslRange(hue=30))
    db.set_image_adjust_json(path, merge_photo_hsl(first, hsl))
    assert photo_color_history_flags(path)["can_undo"] is True
    current = db.get_image_adjust_json(path)
    previous = undo_photo_color(path, current)
    assert previous == first
    db.set_image_adjust_json(path, previous, record_undo=False)
    assert db.get_image_adjust(path).exposure == 5
    assert photo_color_parts(db.get_image_adjust_json(path)).hsl.is_neutral
    nxt = redo_photo_color(path, db.get_image_adjust_json(path))
    assert nxt is not None
    db.set_image_adjust_json(path, nxt, record_undo=False)
    assert photo_color_parts(db.get_image_adjust_json(path)).hsl.red.hue == 30


def test_export_applies_hsl_and_keeps_source_bytes(tmp_path: Path):
    source = _rgb_jpeg(tmp_path / "src.jpg", color=(20, 40, 200), size=(80, 60))
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    hsl = HslAdjust(blue=HslRange(hue=40, saturation=50, luminance=0))
    color_raw = merge_photo_hsl(
        merge_photo_image_adjust(None, ImageAdjust(), look_id=""),
        hsl,
    )
    dest = tmp_path / "out.jpg"
    export_photo_file(source, dest, PRESET_BEST, color_raw=color_raw, still_format="jpeg")
    assert dest.is_file()
    with Image.open(dest) as img:
        assert img.size == (80, 60)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    # Graded export must differ from a neutral byte-copy of the source.
    assert hashlib.sha256(dest.read_bytes()).hexdigest() != before


def test_api_hsl_and_preview(client_with_photo):
    client, media_id, source = client_with_photo
    before = hashlib.sha256(Path(source).read_bytes()).hexdigest()
    res = client.patch(
        f"/api/media/{media_id}/hsl",
        json={"ranges": {"green": {"hue": 15, "saturation": 20, "luminance": -10}}},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["hsl"]["ranges"]["green"]["hue"] == 15
    assert body["needs_server_preview"] is True
    assert body["can_undo"] is True
    preview = client.get(f"/api/media/{media_id}/color-preview")
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/jpeg")
    assert len(preview.content) > 100
    undo = client.post(f"/api/media/{media_id}/color/undo")
    assert undo.status_code == 200
    assert undo.json()["hsl"]["ranges"]["green"]["hue"] == 0
    assert hashlib.sha256(Path(source).read_bytes()).hexdigest() == before


@pytest.fixture
def client_with_photo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    from orga_drone.app import create_app
    from orga_drone.config import Settings

    prefs = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr("orga_drone.app_prefs.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_export.settings", prefs)
    monkeypatch.setattr("orga_drone.config.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_preview_frame.settings", prefs, raising=False)

    root = tmp_path / "lib"
    root.mkdir()
    media = root / "photo.jpg"
    _rgb_jpeg(media)
    app = create_app()
    db: Database = app.state.db
    root_id = db.add_root(root, label="lib")
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": media.name,
            "path": str(media.resolve()),
            "size_bytes": media.stat().st_size,
            "duration_s": None,
            "recorded_at": "2024-01-01T00:00:00",
            "sequence": None,
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
    client = TestClient(app)
    return client, media_id, str(media.resolve())
