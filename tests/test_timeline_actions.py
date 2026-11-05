"""Timeline contracts use the same temporary catalog and Story history as Studio."""
from __future__ import annotations


import subprocess

import pytest

from orga_drone.ffmpeg_bin import find_ffmpeg

from orga_drone.control import ControlError
from orga_drone.db import Database
from orga_drone.studio_history import capture_story, history_flags
from tests.test_control_api import command, execute

from tests.test_studio_history import _seed

pytest_plugins = ["tests.test_control_api"]


def timeline(service, sid, state, action, params):
    cmd = command(service, sid, state, kind="timeline_action")
    cmd.update(action=action, action_version=1, params=params)
    return cmd


def resume(service, sid, state, result):
    resumed = service.resume({"ticket": result["resume_ticket"], "project_id": state["project_id"]})
    state.update(clip_id=resumed["selection_clip_id"], selection_revision=resumed["selection_revision"])
    service.poll({"session_id": sid, "state": state})
    service.acknowledge({"session_id": sid, "command_id": result["command_id"], "preview_status": "refresh_requested"})


def test_add_remove_reorder_trim_undo_redo_reopen_and_source_preservation(control, tmp_path):
    client, db, service, sid, state, headers = control
    pid, a = state["project_id"], state["clip_id"]
    b = _seed(db, tmp_path / "media", "B.MP4", 12, project_id=pid)
    for path in (tmp_path / "media").glob("*.MP4"):
        subprocess.run([find_ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=10", "-t", "12", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True)
    sources = {p: p.read_bytes() for p in (tmp_path / "media").glob("*.MP4")}
    media = db.list_studio_items(pid)[1].media_id
    before = capture_story(db, pid)
    add = timeline(service, sid, state, "timeline.add", {"media_id": media})
    added = execute(service, sid, state, add)
    assert added["persisted"], added
    c = added["affected_clip_id"]
    assert added["canonical"]["ordered_ids"] == [a, b, c]
    assert "resume_ticket" not in service.external_result(add["command_id"])
    resume(service, sid, state, added)
    undo = command(service, sid, state, kind="undo_last_change")
    result = execute(service, sid, state, undo)
    assert result["persisted"], result
    assert capture_story(db, pid) == before
    resume(service, sid, state, result)
    assert client.post("/api/studio/history/redo", headers=headers).json()["ok"]
    assert [i.id for i in db.list_studio_items(pid)] == [a, b, c]
    reorder = execute(service, sid, state, timeline(service, sid, state, "timeline.reorder", {"ordered_ids": [b, c, a]}))
    assert reorder["persisted"], reorder
    resume(service, sid, state, reorder)
    trim = execute(service, sid, state, timeline(service, sid, state, "timeline.trim", {"source_in_s": 1.0, "source_out_s": 4.0}))
    assert trim["persisted"], trim
    assert trim["canonical"]["clips"][-1]["effective_duration_s"] == 3
    resume(service, sid, state, trim)
    saved = capture_story(db, pid)
    reopened = Database(db.path)
    assert capture_story(reopened, pid) == saved
    remove = timeline(service, sid, state, "timeline.remove", {})
    removed = execute(service, sid, state, remove)
    assert removed["persisted"], removed
    resume(service, sid, state, removed)
    assert state["clip_id"] is None
    undo = command(service, sid, state, kind="undo_last_change")
    undo["clip_id"] = a  # Original removed target; never substitute B.
    restored = execute(service, sid, state, undo)
    assert restored["persisted"], restored
    assert capture_story(db, pid) == saved
    assert all(p.read_bytes() == data for p, data in sources.items())


@pytest.mark.parametrize("start,end", [(-1, 2), (2, 1), (1, 1), (0, .01), (True, 2), (0, float("inf")), (float("nan"), 2), (0, 10**400), (10**400, 10**400 + 1)])
def test_invalid_trim_is_atomic(control, start, end):
    _, db, service, sid, state, _ = control
    before = capture_story(db, state["project_id"])
    with pytest.raises(ControlError):
        service.submit(timeline(service, sid, state, "timeline.trim", {"source_in_s": start, "source_out_s": end}))
    assert capture_story(db, state["project_id"]) == before
    assert not history_flags(state["project_id"])["can_undo"]


def test_two_clip_wrong_target_stale_queue_and_undo(control, tmp_path):
    _, db, service, sid, state, _ = control
    pid, a = state["project_id"], state["clip_id"]
    b = _seed(db, tmp_path / "media", "B.MP4", 12, project_id=pid)
    cmd = timeline(service, sid, state, "timeline.trim", {"source_in_s": 1, "source_out_s": 3})
    service.submit(cmd)
    other = dict(state, clip_id=b, selection_revision=2)
    service.poll({"session_id": sid, "state": other})
    rejected = service.execute({"command_id": cmd["command_id"], "session_id": sid, "state": other})
    assert rejected["error_code"] == "STALE_SELECTION"
    state.update(selection_revision=3)
    service.poll({"session_id": sid, "state": state})
    edited = execute(service, sid, state, timeline(service, sid, state, "timeline.trim", {"source_in_s": 1, "source_out_s": 3}))
    resume(service, sid, state, edited)
    other = dict(state, clip_id=b, selection_revision=4)
    service.poll({"session_id": sid, "state": other})
    undo = command(service, sid, other, kind="undo_last_change")
    with pytest.raises(ControlError, match="UNDO_CONFLICT"):
        service.submit(undo)
    assert next(c for c in db.list_studio_items(pid) if c.id == a).source_in_s == 1
    assert next(c for c in db.list_studio_items(pid) if c.id == b).source_in_s is None


def test_ticket_recovery_replay_expiry_and_fingerprint(control):
    _, db, service, sid, state, _ = control
    result = execute(service, sid, state, timeline(service, sid, state, "timeline.trim", {"source_in_s": 1, "source_out_s": 4}))
    recovered = service.recover({"session_id": sid, "command_id": result["command_id"]})
    assert recovered["resume_ticket"] == result["resume_ticket"]
    with pytest.raises(ControlError):
        service.resume({"ticket": result["resume_ticket"], "project_id": state["project_id"] + 1})
    assert len(db.list_studio_items(state["project_id"])) == 1


def test_ticket_is_one_use_and_disable_revokes(control):
    _, _, service, sid, state, _ = control
    result = execute(service, sid, state, timeline(service, sid, state, "timeline.trim", {"source_in_s": 1, "source_out_s": 4}))
    resume(service, sid, state, result)
    with pytest.raises(ControlError, match="INVALID_RESUME_TICKET"):
        service.resume({"ticket": result["resume_ticket"], "project_id": state["project_id"]})
    result = execute(service, sid, state, timeline(service, sid, state, "timeline.trim", {"source_in_s": 2, "source_out_s": 4}))
    service.disable()
    with pytest.raises(ControlError):
        service.resume({"ticket": result["resume_ticket"], "project_id": state["project_id"]})


def test_canonical_failure_rolls_back_rows_and_history(control, monkeypatch):
    _, db, service, sid, state, _ = control
    before = capture_story(db, state["project_id"])
    def fail(*args):
        raise RuntimeError("synthetic snapshot failure")
    monkeypatch.setattr("orga_drone.control.timeline_view", fail)
    result = execute(service, sid, state, timeline(service, sid, state, "timeline.remove", {}))
    assert not result["persisted"] and result["error_code"] == "DATABASE_ERROR"
    assert capture_story(db, state["project_id"]) == before
    assert not history_flags(state["project_id"])["can_undo"]


@pytest.mark.parametrize("fault", ["expiry", "fingerprint"])
def test_resume_rejects_changed_context(control, fault):
    _, db, service, sid, state, _ = control
    result = execute(service, sid, state, timeline(service, sid, state, "timeline.remove", {}))
    if fault == "expiry":
        service.clock = lambda: service.reload_ticket["deadline"] + 1
    elif fault == "fingerprint":
        db.set_studio_project_title(state["project_id"], "changed")
    else:
        from orga_drone.studio_history import invalidate_control_revision
        invalidate_control_revision()
    with pytest.raises(ControlError):
        service.resume({"ticket": result["resume_ticket"], "project_id": state["project_id"]})


def test_ui_api_trim_reorder_parity_and_gesture_grouping(control, tmp_path):
    client, db, service, sid, state, headers = control
    pid, a = state["project_id"], state["clip_id"]
    b = _seed(db, tmp_path / "media", "B.MP4", 12, project_id=pid)
    # Existing UI section changes repeats, API trim preserves it and speed/effects.
    db.set_studio_section(a, source_in_s=0, source_out_s=10, repeats=2)
    db.set_studio_playback_speed(a, .5)
    cmd = timeline(service, sid, state, "timeline.trim", {"source_in_s": 2, "source_out_s": 99})
    result = execute(service, sid, state, cmd)
    assert result["persisted"], result
    api_clip = next(c for c in db.list_studio_items(pid) if c.id == a)
    resume(service, sid, state, result)
    undo = execute(service, sid, state, command(service, sid, state, kind="undo_last_change"))
    resume(service, sid, state, undo)
    response = client.patch(f"/api/studio/{a}/section", json={"source_in_s": 2, "source_out_s": 99, "repeats": 2}, headers=dict(headers, **{"X-Studio-History-Group": "trim-gesture"}))
    assert response.status_code == 200, response.text
    ui_clip = next(c for c in db.list_studio_items(pid) if c.id == a)
    assert (ui_clip.source_in_s, ui_clip.source_out_s, ui_clip.effect_settings) == (api_clip.source_in_s, api_clip.source_out_s, api_clip.effect_settings)
    assert response.json()["effective_duration_s"] == result["canonical"]["clips"][0]["effective_duration_s"]
    response = client.post("/api/studio/reorder", json={"ordered_ids": [b, a]}, headers=headers)
    assert response.status_code == 200
    assert [c.id for c in db.list_studio_items(pid)] == [b, a]
    before = capture_story(db, pid)
    invalid = execute(service, sid, state, timeline(service, sid, state, "timeline.reorder", {"ordered_ids": [a]}))
    assert invalid["error_code"] == "INVALID_PARAMS"
    assert capture_story(db, pid) == before


def test_ui_add_remove_shared_history_and_duplicate_source(control):
    client, db, _, _, state, headers = control
    pid, a = state["project_id"], state["clip_id"]
    mid = db.list_studio_items(pid)[0].media_id
    response = client.post(f"/media/{mid}/studio/add", data={"return_to": "studio"}, headers=headers, follow_redirects=False)
    assert response.status_code == 303
    clips = db.list_studio_items(pid)
    assert len(clips) == 2 and clips[0].id == a and clips[1].media_id == mid
    assert client.post("/api/studio/history/undo", headers=headers).json()["ok"]
    assert len(db.list_studio_items(pid)) == 1
    assert client.post("/api/studio/history/redo", headers=headers).json()["ok"]
    b = db.list_studio_items(pid)[1].id
    assert client.post(f"/studio/{b}/remove", headers=headers, follow_redirects=False).status_code == 303
    assert len(db.list_studio_items(pid)) == 1
    assert client.post("/api/studio/history/undo", headers=headers).json()["ok"]
    assert [c.id for c in db.list_studio_items(pid)] == [a, b]


def test_expired_reload_ticket_does_not_wedge_timeline(control):
    _, _, service, sid, state, _ = control
    first = execute(
        service,
        sid,
        state,
        timeline(service, sid, state, "timeline.trim", {"source_in_s": 1, "source_out_s": 4}),
    )
    assert first["persisted"]
    service.reload_ticket["deadline"] = service.clock() - 1
    service.poll({"session_id": sid, "state": state})
    second = execute(
        service,
        sid,
        state,
        timeline(service, sid, state, "timeline.trim", {"source_in_s": 2, "source_out_s": 5}),
    )
    assert second["persisted"], second
    assert service.reload_ticket is not None


def test_unrelated_history_revision_does_not_block_resume(control):
    _, _, service, sid, state, _ = control
    from orga_drone.studio_history import invalidate_control_revision

    result = execute(
        service,
        sid,
        state,
        timeline(service, sid, state, "timeline.trim", {"source_in_s": 1, "source_out_s": 4}),
    )
    invalidate_control_revision()
    resumed = service.resume(
        {"ticket": result["resume_ticket"], "project_id": state["project_id"]}
    )
    assert resumed["selection_clip_id"] == state["clip_id"]


def test_noop_timeline_keeps_prior_undo_and_skips_reload(control, tmp_path):
    _, db, service, sid, state, _ = control
    pid, a = state["project_id"], state["clip_id"]
    b = _seed(db, tmp_path / "media", "B.MP4", 12, project_id=pid)
    before = capture_story(db, pid)
    first = execute(
        service,
        sid,
        state,
        timeline(service, sid, state, "timeline.trim", {"source_in_s": 1, "source_out_s": 4}),
    )
    resume(service, sid, state, first)
    noop = timeline(
        service,
        sid,
        state,
        "timeline.reorder",
        {"ordered_ids": [a, b]},
    )
    noop["clip_id"] = None
    result = execute(service, sid, state, noop)
    assert result["persisted"] and result["no_op"]
    assert result["reload_required"] is False
    assert "resume_ticket" not in result
    ack = service.acknowledge(
        {
            "session_id": sid,
            "command_id": result["command_id"],
            "preview_status": "unavailable",
        }
    )
    assert ack["ui_applied"]
    undo = execute(
        service, sid, state, command(service, sid, state, kind="undo_last_change")
    )
    assert undo["persisted"], undo
    assert capture_story(db, pid) == before


def test_story_scope_reorder_can_omit_selected_clip_identity(control, tmp_path):
    _, db, service, sid, state, _ = control
    pid, a = state["project_id"], state["clip_id"]
    b = _seed(db, tmp_path / "media", "B.MP4", 12, project_id=pid)
    cmd = timeline(
        service, sid, state, "timeline.reorder", {"ordered_ids": [b, a]}
    )
    cmd["clip_id"] = None
    result = execute(service, sid, state, cmd)
    assert result["persisted"], result
    assert [c.id for c in db.list_studio_items(pid)] == [b, a]


def test_offline_catalog_add_and_trim_keep_existing_behavior(control, tmp_path):
    client, db, service, sid, state, headers = control
    pid = state["project_id"]
    source_clip = _seed(db, tmp_path / "offline", "OFF.MP4", 12, project_id=pid)
    item = next(c for c in db.list_studio_items(pid) if c.id == source_clip)
    media_id = item.media_id
    (tmp_path / "offline" / "OFF.MP4").unlink()
    response = client.post(
        f"/media/{media_id}/studio/add",
        data={"return_to": "studio"},
        headers=headers,
        follow_redirects=False,
    )
    assert response.status_code == 303
    added = db.list_studio_items(pid)[-1].id
    offline_state = dict(
        state, clip_id=added, selection_revision=state["selection_revision"] + 1
    )
    service.poll({"session_id": sid, "state": offline_state})
    trim = execute(
        service,
        sid,
        offline_state,
        timeline(
            service,
            sid,
            offline_state,
            "timeline.trim",
            {"source_in_s": 1, "source_out_s": 4},
        ),
    )
    assert trim["persisted"], trim
    trimmed = next(c for c in db.list_studio_items(pid) if c.id == added)
    assert (trimmed.source_in_s, trimmed.source_out_s) == (1.0, 4.0)
