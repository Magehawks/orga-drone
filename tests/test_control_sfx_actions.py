"""Project-scoped SFX commands through the Control API (issue #281).

sfx.append/update/remove call the same database methods as the Studio
routes and record a Story history step. Responses carry placement only,
never the source path. A change fences the editor session, so each
command reopens that session the way a reload does.
"""

from __future__ import annotations

import secrets
import time

import pytest

from orga_drone.control import ControlError
from orga_drone.studio_history import redo_story, undo_story
from tests.test_studio_history import _client, _seed


@pytest.fixture
def sfx_env(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    client, db = _client(tmp_path, monkeypatch)
    _seed(db, tmp_path / "videos", "SFX.MP4", 12.0)
    project = db.resolve_studio_page_project()
    assert project is not None
    sounds = tmp_path / "sounds"
    sounds.mkdir()
    hit = sounds / "hit.wav"
    hit.write_bytes(b"RIFF-fake")
    db._probe_music_duration_s = lambda _path: 4.0  # type: ignore[method-assign]
    return client, db, project.id, hit


def _open_session(client, project_id: int, clip_id: int | None, *, session_id: str):  # type: ignore[no-untyped-def]
    service = client.app.state.control  # type: ignore[attr-defined]
    key = secrets.token_hex(32)
    assert (
        client.post(
            "/api/studio/control/enable",
            json={"session_id": session_id, "pairing_key": key},
            headers={"Origin": "http://testserver"},
        ).status_code
        == 200
    )
    state = {
        "project_id": project_id,
        "clip_id": clip_id,
        "selection_revision": 1,
        "playhead_s": 0,
        "playing": False,
        "busy": False,
        "ready": True,
    }
    service.poll({"session_id": session_id, "state": state})
    return service, session_id, state


def _cmd(service, sid, state, action, params):  # type: ignore[no-untyped-def]
    return {
        "command_id": secrets.token_hex(8),
        "type": "project_action",
        "action": action,
        "action_version": 1,
        "params": params,
        "session_id": sid,
        "project_id": state["project_id"],
        "clip_id": None,
        "expected_state_token": service.editor_state()["state_token"],
        "expires_at": time.time() + 20,
    }


def _execute(service, sid, state, cmd):  # type: ignore[no-untyped-def]
    service.submit(cmd)
    return service.execute(
        {"session_id": sid, "state": state, "command_id": cmd["command_id"]}
    )


def _placement(**overrides: float) -> dict[str, float]:
    params = {
        "start_s": 1.5,
        "source_in_s": 0.2,
        "source_out_s": 1.4,
        "volume": 0.4,
        "fade_in_s": 0.1,
        "fade_out_s": 0.2,
    }
    params.update(overrides)
    return params


def test_sfx_append_update_remove_and_undo(sfx_env) -> None:  # type: ignore[no-untyped-def]
    client, db, pid, hit = sfx_env
    items = db.list_studio_items(pid)
    selected = items[0].id if items else None
    service, sid, state = _open_session(
        client, pid, selected, session_id="sfx-editor"
    )
    appended = _execute(
        service, sid, state,
        _cmd(service, sid, state, "sfx.append", {
            "file_path": str(hit.resolve()),
            "start_s": 2.5,
        }),
    )
    assert appended["status"] == "persisted", appended
    assert appended["can_undo"] is True
    assert appended["navigation_required"] is True
    assert "file_path" not in str(appended["canonical"])
    assert hit.read_bytes() == b"RIFF-fake"
    clips = db.list_studio_sfx(pid)
    assert len(clips) == 1
    assert clips[0].start_s == pytest.approx(2.5)
    clip_id = clips[0].id

    service, sid, state = _open_session(
        client, pid, selected, session_id="sfx-editor"
    )
    updated = _execute(
        service, sid, state,
        _cmd(service, sid, state, "sfx.update", {
            "clip_id": clip_id, **_placement(),
        }),
    )
    assert updated["status"] == "persisted", updated
    fresh = db.get_studio_sfx_clip(pid, clip_id)
    assert fresh is not None
    assert fresh.start_s == pytest.approx(1.5)
    assert fresh.source_in_s == pytest.approx(0.2)
    assert fresh.source_out_s == pytest.approx(1.4)
    assert fresh.volume == pytest.approx(0.4)

    assert undo_story(db, pid) is True
    restored = db.get_studio_sfx_clip(pid, clip_id)
    assert restored is not None
    assert restored.start_s == pytest.approx(2.5)
    assert redo_story(db, pid) is True
    redone = db.get_studio_sfx_clip(pid, clip_id)
    assert redone is not None
    assert redone.start_s == pytest.approx(1.5)

    service, sid, state = _open_session(
        client, pid, selected, session_id="sfx-editor"
    )
    removed = _execute(
        service, sid, state,
        _cmd(service, sid, state, "sfx.remove", {"clip_id": clip_id}),
    )
    assert removed["status"] == "persisted", removed
    assert db.list_studio_sfx(pid) == []
    assert hit.is_file()


def test_sfx_rejects_missing_file_bad_trim_and_unknown_clip(sfx_env) -> None:  # type: ignore[no-untyped-def]
    client, db, pid, hit = sfx_env
    items = db.list_studio_items(pid)
    selected = items[0].id if items else None
    service, sid, state = _open_session(
        client, pid, selected, session_id="sfx-editor"
    )
    missing = _execute(
        service, sid, state,
        _cmd(service, sid, state, "sfx.append", {
            "file_path": str(hit.parent / "missing.wav"),
            "start_s": 1.0,
        }),
    )
    assert missing["status"] == "rejected", missing
    assert missing["error_code"] == "INVALID_PAYLOAD"
    assert db.list_studio_sfx(pid) == []

    service, sid, state = _open_session(
        client, pid, selected, session_id="sfx-editor"
    )
    with pytest.raises(ControlError) as excinfo:
        service.submit(_cmd(service, sid, state, "sfx.update", {
            "clip_id": 1,
            **_placement(source_in_s=1.0, source_out_s=1.0),
        }))
    assert excinfo.value.code == "INVALID_PARAMS"
    assert db.list_studio_sfx(pid) == []

    service, sid, state = _open_session(
        client, pid, selected, session_id="sfx-editor"
    )
    unknown = _execute(
        service, sid, state,
        _cmd(service, sid, state, "sfx.remove", {"clip_id": 999999}),
    )
    assert unknown["status"] == "rejected", unknown
    assert unknown["error_code"] == "TARGET_NOT_FOUND"
