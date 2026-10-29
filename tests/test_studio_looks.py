"""Studio Quick Looks and before/after contract (Issue #175)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.app import create_app
from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.studio_image import image_adjust_from_effect_settings
from orga_drone.studio_looks import (
    LOOK_IDS,
    look_id_from_effect_settings,
    look_image_adjust,
    parse_look_payload,
    quick_looks_preview_model,
)


def test_look_catalog_covers_named_presets() -> None:
    model = quick_looks_preview_model()
    assert model["ids"] == list(LOOK_IDS)
    for look_id in LOOK_IDS:
        adjust = look_image_adjust(look_id)
        assert adjust.as_dict() == model["values"][look_id]
    assert look_image_adjust("natural").is_neutral
    assert look_image_adjust("black_and_white").saturation == -100
    with pytest.raises(ValueError):
        look_image_adjust("unknown")
    assert parse_look_payload({"id": "cinematic"}) == "cinematic"
    assert parse_look_payload({"id": ""}) == ""


def test_quick_look_replaces_sliders_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    app = create_app()
    db: Database = app.state.db
    root = tmp_path / "lib"
    root.mkdir()
    root_id = db.add_root(root, label="t")
    photo = root / "p.jpg"
    photo.write_bytes(b"jpg")
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": photo.name,
            "path": str(photo.resolve()),
            "size_bytes": 3,
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
    item = db.get_media(media_id)
    assert item is not None
    clip_id, _ = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
    )
    db.set_studio_image_adjust(clip_id, {"exposure": 40, "warmth": -20})
    client = TestClient(app)
    page = client.get("/studio")
    assert 'id="inspector-quick-look"' in page.text
    assert 'id="inspector-look-compare"' in page.text
    assert "compareBeforeAfter" in client.get("/static/js/studio.js").text

    applied = client.patch(f"/api/studio/{clip_id}/look", json={"id": "vibrant"})
    assert applied.status_code == 200
    body = applied.json()
    assert body["quick_look"] == "vibrant"
    assert body["image"] == look_image_adjust("vibrant").as_dict()
    stored = {row.id: row for row in db.list_studio_items()}[clip_id]
    assert look_id_from_effect_settings(stored.effect_settings) == "vibrant"
    assert image_adjust_from_effect_settings(stored.effect_settings).as_dict() == body[
        "image"
    ]

    cleared = client.patch(f"/api/studio/{clip_id}/look", json={"id": ""})
    assert cleared.status_code == 200
    assert cleared.json()["quick_look"] == ""
    kept = {row.id: row for row in db.list_studio_items()}[clip_id]
    assert look_id_from_effect_settings(kept.effect_settings) == ""
    assert image_adjust_from_effect_settings(kept.effect_settings).as_dict() == body[
        "image"
    ]
