"""Project-scoped music commands through the Control API (issue #281 part 2).

music.append/update/remove/reorder/set_start mirror the UI routes exactly
(same DB methods, same error semantics; set_start is a story-history edit,
the others are not). A music change reloads the editor (navigation + fence)
like project.open, because the soundtrack view becomes stale â€” so each
command runs in a fresh editor session, exactly like a user reload.
"""

from __future__ import annotations

import secrets
import time

import pytest

from orga_drone.control import ControlError
from tests.test_studio_history import _client, _seed


@pytest.fixture
def music_env(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """App + DB + one music file; each test opens its own editor session."""
    client, db = _client(tmp_path, monkeypatch)
    _seed(db, tmp_path / "videos", "MUSIC.MP4", 12.0)
    project = db.resolve_studio_page_project()
    assert project is not None
    music = tmp_path / "music"
    music.mkdir(exist_ok=True)
    song = music / "bed.mp3"
    song.write_bytes(b"ID3fake")
    db._probe_music_duration_s = lambda _path: 30.0  # type: ignore[method-assign,assignment]
    return client, db, project.id, song


def _open_session(client, project_id: int, clip_id: int | None, *, session_id: str | None = None):  # type: ignore[no-untyped-def]
    """Enable + poll one editor session. Re-enabling with the SAME session
    id is the UI-reload equivalent (a different id while the previous lease
    is alive is an EDITOR_SESSION_CONFLICT by design)."""
    service = client.app.state.control  # type: ignore[attr-defined]
    key = secrets.token_hex(32)
    sid = session_id or f"music-editor-{secrets.token_hex(4)}"
    assert (
        client.post(
            "/api/studio/control/enable",
            json={"session_id": sid, "pairing_key": key},
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
    service.poll({"session_id": sid, "state": state})
    return service, sid, state


def _music_cmd(service, sid, state, action, params, cid=None):  # type: ignore[no-untyped-def]
    return {
        "command_id": cid or secrets.token_hex(8),
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


def test_music_append_update_set_start_remove_roundtrip(music_env) -> None:  # type: ignore[no-untyped-def]
    client, db, pid, song = music_env
    items = db.list_studio_items(pid)
    clip_id_for_state = items[0].id if items else None
    service, sid, state = _open_session(client, pid, clip_id_for_state, session_id="music-editor-main")

    appended = _execute(service, sid, state, _music_cmd(
        service, sid, state, "music.append", {"file_path": str(song.resolve())}
    ))
    assert appended["status"] == "persisted", appended
    assert appended["navigation_required"] is True
    assert song.read_bytes() == b"ID3fake"  # source file untouched

    tracks = db.list_studio_music(pid)
    assert len(tracks) == 1
    music_clip_id = tracks[0].id

    service, sid, state = _open_session(client, pid, clip_id_for_state, session_id="music-editor-main")
    updated = _execute(service, sid, state, _music_cmd(
        service, sid, state, "music.update",
        {"clip_id": music_clip_id, "volume": 0.5, "fade_in_s": 1.0,
         "fade_out_s": 2.0, "loop": False},
    ))
    assert updated["status"] == "persisted", updated
    fresh = db.get_studio_music_clip(pid, music_clip_id)
    assert fresh is not None
    assert fresh.volume == pytest.approx(0.5)
    assert fresh.fade_in_s == pytest.approx(1.0)
    assert fresh.loop is False

    service, sid, state = _open_session(client, pid, clip_id_for_state, session_id="music-editor-main")
    started = _execute(service, sid, state, _music_cmd(
        service, sid, state, "music.set_start", {"start_s": 5.0}
    ))
    assert started["status"] == "persisted", started
    project = db.get_open_studio_project()
    assert project is not None
    assert project.music_start_s == pytest.approx(5.0)

    service, sid, state = _open_session(client, pid, clip_id_for_state, session_id="music-editor-main")
    removed = _execute(service, sid, state, _music_cmd(
        service, sid, state, "music.remove", {"clip_id": music_clip_id}
    ))
    assert removed["status"] == "persisted", removed
    assert db.list_studio_music(pid) == []


def test_music_reorder(music_env) -> None:  # type: ignore[no-untyped-def]
    client, db, pid, song = music_env
    items = db.list_studio_items(pid)
    service, sid, state = _open_session(client, pid, items[0].id if items else None, session_id="music-editor-main")
    db.append_studio_music(pid, str(song.resolve()))
    second = song.parent / "second.mp3"
    second.write_bytes(b"ID3second")
    db.append_studio_music(pid, str(second.resolve()))
    tracks = db.list_studio_music(pid)

    service, sid, state = _open_session(client, pid, items[0].id if items else None, session_id="music-editor-main")
    reordered = _execute(service, sid, state, _music_cmd(
        service, sid, state, "music.reorder",
        {"ordered_ids": [tracks[1].id, tracks[0].id]},
    ))
    assert reordered["status"] == "persisted", reordered
    after = db.list_studio_music(pid)
    assert [t.id for t in after] == [tracks[1].id, tracks[0].id]


def test_music_rejects_bad_params_and_stale_state(music_env) -> None:  # type: ignore[no-untyped-def]
    client, db, pid, song = music_env
    items = db.list_studio_items(pid)
    clip_id_for_state = items[0].id if items else None
    service, sid, state = _open_session(client, pid, clip_id_for_state, session_id="music-editor-main")

    # Unknown file: payload problem, not database fault.
    rejected = _execute(service, sid, state, _music_cmd(
        service, sid, state, "music.append",
        {"file_path": str(song.parent / "missing.mp3")},
    ))
    assert rejected["status"] == "rejected", rejected
    assert rejected["error_code"] == "INVALID_PAYLOAD"

    # Wrong params shape: submit raises with a typed code.
    service, sid, state = _open_session(client, pid, clip_id_for_state, session_id="music-editor-main")
    with pytest.raises(ControlError) as excinfo:
        service.submit(_music_cmd(
            service, sid, state, "music.append", {"path": str(song.resolve())}
        ))
    assert excinfo.value.code == "INVALID_PARAMS"

    # Stale state token: no mutation.
    service, sid, state = _open_session(client, pid, clip_id_for_state, session_id="music-editor-main")
    stale = _music_cmd(service, sid, state, "music.append",
                       {"file_path": str(song.resolve())})
    stale["expected_state_token"] = "0" * 64
    with pytest.raises(ControlError) as excinfo:
        service.submit(stale)
    assert excinfo.value.code == "STALE_STATE"
    assert db.list_studio_music(pid) == []
