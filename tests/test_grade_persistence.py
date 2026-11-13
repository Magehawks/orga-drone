"""Canonical grade persistence, write guards, and wrapping (#351)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orga_drone.db import Database, make_identity_key
from orga_drone.grade_backup import create_backup
from orga_drone.studio_actions import (
    ActionValidationError,
    prepare_action,
)
from orga_drone.studio_actions import ACTION_SPECS
from orga_drone.studio_grade_contract import GradeError, LEGACY_KEYS
from orga_drone.studio_grade_model import read_grade
from orga_drone.studio_grade_persistence import (
    grade_write_guard,
    is_canonical_effect_settings,
    publish_grade_document,
    require_writes_enabled,
    startup_backup_if_needed,
    wrap_legacy_to_canonical,
    writes_enabled,
)


def _legacy_blob() -> str:
    return json.dumps(
        {
            "image": {
                "exposure": 12,
                "contrast": 0,
                "saturation": 0,
                "warmth": 0,
                "highlights": 0,
                "shadows": 0,
                "blacks": 0,
            },
            "color": {
                "input_profile": "rec709",
                "creative_lut": None,
                "creative_strength": 100,
                "conversion_lut": None,
                "conversion_confirmed": False,
            },
            "overlays": [],
            "mystery": {"keep": True},
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _seed_photo(db: Database, root_path: Path) -> int:
    root_path.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root_path, label="grade-persist")
    media_file = root_path / "clip.jpg"
    media_file.write_bytes(b"media")
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": "clip.jpg",
            "path": str(media_file.resolve()),
            "size_bytes": 5,
            "duration_s": None,
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


def test_guard_allows_legacy_and_blocks_canonical() -> None:
    grade_write_guard("{}")
    grade_write_guard(_legacy_blob())
    wrapped = wrap_legacy_to_canonical(_legacy_blob())
    with pytest.raises(GradeError, match="CANONICAL_GUARD"):
        grade_write_guard(json.dumps(wrapped))


def test_wrap_moves_legacy_keys_and_preserves_others() -> None:
    document = wrap_legacy_to_canonical(_legacy_blob())
    model = read_grade(document)
    assert model.authority == "canonical"
    assert model.evaluator == "legacy-v1"
    assert model.revision == 1
    root = model.to_dict()
    for key in LEGACY_KEYS:
        assert key not in root
    assert root["mystery"] == {"keep": True}
    assert root["overlays"] == []
    step = root["grade"]["steps"][0]
    assert step["type"] == "legacy-stack-v1"
    assert step["params"]["image"]["exposure"] == 12
    assert "color" in step["params"]


def test_wrap_rejects_already_canonical() -> None:
    document = wrap_legacy_to_canonical(_legacy_blob())
    with pytest.raises(GradeError, match="already canonical"):
        wrap_legacy_to_canonical(document)


def test_publish_bumps_revision_and_rejects_stale() -> None:
    document = wrap_legacy_to_canonical(_legacy_blob())
    current = read_grade(document)
    proposed = current.to_dict()
    proposed["grade"]["steps"][0]["enabled"] = False
    with pytest.raises(GradeError, match="STALE_REVISION"):
        publish_grade_document(current, proposed, expected_revision=0)
    blob = publish_grade_document(current, proposed, expected_revision=1)
    updated = read_grade(blob)
    assert updated.revision == 2
    assert updated.steps[0]["enabled"] is False


def test_startup_backup_enables_writes(tmp_path: Path) -> None:
    live = tmp_path / "orga-drone.sqlite3"
    Database(live)
    assert writes_enabled(tmp_path) is False
    with pytest.raises(GradeError):
        require_writes_enabled(tmp_path)
    manifest = startup_backup_if_needed(tmp_path, app_version="2.3.3-test")
    assert manifest is not None
    assert writes_enabled(tmp_path) is True
    again = startup_backup_if_needed(tmp_path, app_version="2.3.3-test")
    assert again is not None
    assert again["sha256"] == manifest["sha256"]


def test_db_wrap_and_legacy_setter_guard(tmp_path: Path) -> None:
    live = tmp_path / "orga-drone.sqlite3"
    db = Database(live)
    create_backup(live, tmp_path / "recovery" / "pre-grade-migration", app_version="t")
    startup_backup_if_needed(tmp_path, app_version="t")
    media_id = _seed_photo(db, tmp_path / "library")
    item = db.get_media(media_id)
    assert item is not None
    clip_id, _created = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
    )
    db.set_studio_image_adjust(clip_id, {"exposure": 10})
    wrapped = db.wrap_studio_grade(clip_id)
    assert is_canonical_effect_settings(wrapped.effect_settings)
    with pytest.raises(GradeError, match="CANONICAL_GUARD"):
        db.set_studio_image_adjust(clip_id, {"exposure": 20})
    current = read_grade(wrapped.effect_settings)
    proposed = current.to_dict()
    proposed["grade"]["steps"][0]["mix"] = 1
    saved = db.set_studio_canonical_grade(
        clip_id, proposed, expected_revision=current.revision
    )
    assert read_grade(saved.effect_settings).revision == current.revision + 1


def test_prepare_action_blocks_canonical_color() -> None:
    document = wrap_legacy_to_canonical(_legacy_blob())
    raw = json.dumps(document)
    spec = next(item for item in ACTION_SPECS if item.name == "clip.color.image")
    with pytest.raises(ActionValidationError) as exc:
        prepare_action(spec, raw, {"exposure": 1}, set(), Path("."))
    assert exc.value.args[0] == "CANONICAL_GUARD"
