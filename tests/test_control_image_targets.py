"""Image (photo) targets for the shared color actions (issue #296).

The shared actions and Control API previously rejected photo clips with
UNSUPPORTED_CLIP although the Studio image editor, the color routes, the
preview-still path and the export chain genuinely support photos. These
tests pin the honest image-target support: same actions, same validation,
same persistence â€” no duplicated logic.
"""

from __future__ import annotations

import secrets
import time
from pathlib import Path

import pytest

from orga_drone.db import make_identity_key
from orga_drone.studio_actions import ACTION_SPECS
from orga_drone.studio_color_wheels import color_wheels_from_effect_settings
from orga_drone.studio_image import image_adjust_from_effect_settings
from tests.test_studio_history import _client


def _seed_photo(db, root: Path, filename: str = "PHOTO.JPG") -> int:  # type: ignore[no-untyped-def]
    """Seed one real photo clip (reuses the established media seeding)."""
    from PIL import Image

    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label=filename)
    media_file = root / filename
    Image.new("RGB", (320, 240), (180, 100, 60)).save(media_file, format="JPEG")
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": filename,
            "path": str(media_file.resolve()),
            "size_bytes": media_file.stat().st_size,
            "duration_s": None,
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


def test_color_action_specs_target_media_clips() -> None:
    """The five photo-capable color actions advertise honest targets."""
    targets = {spec.name: spec.target for spec in ACTION_SPECS}
    for name in (
        "clip.color.image",
        "clip.color.look",
        "clip.color.hsl",
        "clip.color.wheels",
        "clip.effects.detail",
    ):
        assert targets[name] == "media_clip", name
    # The v1 properties command keeps its video target (existing semantics).
    assert targets["clip.color.properties"] == "video_clip"


@pytest.fixture
def photo_control(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """A Control API session with a photo clip selected (ready state)."""
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed_photo(db, tmp_path / "photos")
    pid = db.list_studio_items()[0].project_id
    service = client.app.state.control  # type: ignore[attr-defined]
    key = secrets.token_hex(32)
    sid = "test-photo-editor"
    origin = {"Origin": "http://testserver"}
    assert (
        client.post(
            "/api/studio/control/enable",
            json={"session_id": sid, "pairing_key": key},
            headers=origin,
        ).status_code
        == 200
    )
    state = {
        "project_id": pid,
        "clip_id": clip_id,
        "selection_revision": 1,
        "playhead_s": 0,
        "playing": False,
        "busy": False,
        "ready": True,
    }
    service.poll({"session_id": sid, "state": state})
    headers = dict(origin, Authorization="Bearer " + key)
    return client, db, service, sid, state, headers, clip_id


def _execute(service, sid, state, cmd):  # type: ignore[no-untyped-def]
    service.submit(cmd)
    return service.execute(
        {"session_id": sid, "state": state, "command_id": cmd["command_id"]}
    )


def test_editor_state_reports_photo_clip_ready(photo_control) -> None:  # type: ignore[no-untyped-def]
    """The issue's core complaint: a selected photo must NOT report
    ready=false/UNSUPPORTED_CLIP for the editor state."""
    _client_result, _db, service, sid, state, _headers, _clip_id = photo_control
    editor = service.editor_state()
    assert editor["ready"] is True, editor
    assert editor["properties"] is not None


def test_color_actions_persist_on_photo_clip(photo_control) -> None:  # type: ignore[no-untyped-def]
    """apply_action with the shared color actions works on a photo target."""
    _client_result, db, service, sid, state, _headers, clip_id = photo_control
    actions = [
        ("clip.color.image", {"exposure": 30}),
        ("clip.color.hsl", {"ranges": {"green": {"saturation": -60}}}),
        ("clip.color.wheels", {"wheels": {"highlights": {"x": 0.3}}}),
        ("clip.effects.detail", {"sharpen": 25}),
    ]
    for action, params in actions:
        result = _execute(
            service, sid, state,
            {
                "command_id": secrets.token_hex(8),
                "type": "apply_action",
                "action": action,
                "action_version": 1,
                "params": params,
                "session_id": sid,
                "project_id": state["project_id"],
                "clip_id": clip_id,
                "expected_state_token": service.editor_state()["state_token"],
                "expires_at": time.time() + 20,
            },
        )
        assert result["persisted"] is True, (action, result)
    stored = {item.id: item for item in db.list_studio_items()}[clip_id]
    settings = stored.effect_settings
    assert image_adjust_from_effect_settings(settings).exposure == 30
    assert color_wheels_from_effect_settings(settings).highlights.x == pytest.approx(0.3)


def test_photo_color_persistence_after_reopen(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Applied photo color settings survive a database reopen."""
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed_photo(db, tmp_path / "photos")
    assert client.patch(
        f"/api/studio/{clip_id}/color-wheels",
        json={"wheels": {"highlights": {"x": 0.3}}},
    ).status_code == 200
    from orga_drone.db import Database

    reopened = Database(db.path)
    stored = {item.id: item for item in reopened.list_studio_items()}[clip_id]
    wheels = color_wheels_from_effect_settings(stored.effect_settings)
    assert wheels.highlights.x == pytest.approx(0.3)


def test_title_cards_stay_unsupported(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Title cards and other non-media items report UNSUPPORTED_CLIP through
    editor_state (ready=false + typed error), never a valid target."""
    client, db = _client(tmp_path, monkeypatch)
    _seed_photo(db, tmp_path / "photos")
    project = db.resolve_studio_page_project()
    assert project is not None
    card = client.post("/api/studio/title-cards")
    assert card.status_code == 200
    card_id = int(card.json()["id"])
    service = client.app.state.control  # type: ignore[attr-defined]
    key = secrets.token_hex(32)
    sid = "test-card-editor"
    assert (
        client.post(
            "/api/studio/control/enable",
            json={"session_id": sid, "pairing_key": key},
            headers={"Origin": "http://testserver"},
        ).status_code
        == 200
    )
    state = {
        "project_id": project.id,
        "clip_id": card_id,
        "selection_revision": 1,
        "playhead_s": 0,
        "playing": False,
        "busy": False,
        "ready": True,
    }
    service.poll({"session_id": sid, "state": state})
    editor = service.editor_state()
    assert editor["ready"] is False
    assert editor["error_code"] == "UNSUPPORTED_CLIP"
