"""Studio Quick Looks and before/after contract (Issue #175)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.app import create_app
from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.studio_image import (
    ImageAdjust,
    image_adjust_from_effect_settings,
    image_adjust_from_stored,
)
from orga_drone.studio_looks import (
    LOOK_IDS,
    dump_photo_adjust,
    look_id_from_effect_settings,
    look_id_from_stored,
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
    assert "createColorCompare" in client.get("/static/js/studio.js").text

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


def test_quick_look_out_of_order_writes_last_commit_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prove unsynchronized Look writes persist last-commit-wins on the server.

    The Studio UI now serializes Look PATCH calls and skips superseded intents
    before fetch. This test documents the DB race that remains if two writers
    bypass that queue, and checks save/reopen after a deliberate reverse finish.
    """
    import threading

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

    release_older = threading.Event()
    newer_done = threading.Event()
    errors: list[BaseException] = []

    def write_older() -> None:
        try:
            release_older.wait(timeout=2)
            db.set_studio_quick_look(clip_id, {"id": "cinematic"})
        except BaseException as exc:  # noqa: BLE001 - collect thread failures
            errors.append(exc)

    def write_newer() -> None:
        try:
            db.set_studio_quick_look(clip_id, {"id": "vibrant"})
            newer_done.set()
            release_older.set()
        except BaseException as exc:  # noqa: BLE001 - collect thread failures
            errors.append(exc)

    older = threading.Thread(target=write_older)
    newer = threading.Thread(target=write_newer)
    older.start()
    newer.start()
    older.join(timeout=3)
    newer.join(timeout=3)
    assert not errors
    assert newer_done.is_set()

    stored = {row.id: row for row in db.list_studio_items()}[clip_id]
    # Older commit finished last and overwrote the newer Look.
    assert look_id_from_effect_settings(stored.effect_settings) == "cinematic"
    assert (
        image_adjust_from_effect_settings(stored.effect_settings).as_dict()
        == look_image_adjust("cinematic").as_dict()
    )

    # Save/reopen through a fresh Database handle keeps the last commit.
    reopened = Database(Settings(data_dir=tmp_path / "data").db_path)
    again = {row.id: row for row in reopened.list_studio_items()}[clip_id]
    assert look_id_from_effect_settings(again.effect_settings) == "cinematic"


def test_quick_look_serialized_client_order_keeps_latest_on_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When Look writes run in intent order, reopen matches the latest Look."""
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
    client = TestClient(app)
    first = client.patch(f"/api/studio/{clip_id}/look", json={"id": "cinematic"})
    second = client.patch(f"/api/studio/{clip_id}/look", json={"id": "vibrant"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["quick_look"] == "vibrant"
    stored = {row.id: row for row in db.list_studio_items()}[clip_id]
    assert look_id_from_effect_settings(stored.effect_settings) == "vibrant"
    reopened = Database(Settings(data_dir=tmp_path / "data").db_path)
    again = {row.id: row for row in reopened.list_studio_items()}[clip_id]
    assert look_id_from_effect_settings(again.effect_settings) == "vibrant"
    assert (
        image_adjust_from_effect_settings(again.effect_settings).as_dict()
        == look_image_adjust("vibrant").as_dict()
    )


def test_dump_photo_adjust_keeps_legacy_flat_json_readable() -> None:
    legacy = '{"contrast": 10, "exposure": 5, "saturation": 0, "warmth": -2}'
    assert look_id_from_stored(legacy) == ""
    loaded = image_adjust_from_stored(legacy)
    assert loaded.exposure == 5
    assert loaded.contrast == 10
    assert loaded.highlights == 0

    rich = dump_photo_adjust(
        ImageAdjust(exposure=2, contrast=16, saturation=38, warmth=4, highlights=8),
        "vibrant",
    )
    assert look_id_from_stored(rich) == "vibrant"
    again = image_adjust_from_stored(rich)
    assert again.saturation == 38
    assert again.highlights == 8
