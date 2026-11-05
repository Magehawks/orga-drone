"""Synthetic local Control API contract, transaction, history and security tests."""

from __future__ import annotations

import json
import secrets
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from orga_drone.control import ControlError, ControlService
from orga_drone.studio_history import history_flags, redo_story
from tests.test_studio_history import _client, _seed


@pytest.fixture
def control(tmp_path, monkeypatch):
    client, db = _client(tmp_path, monkeypatch)
    cid = _seed(db, tmp_path / "media", "synthetic.MP4", 10)
    pid = db.list_studio_items()[0].project_id
    service = client.app.state.control
    key = secrets.token_hex(32)
    sid = "test-editor"
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
        "clip_id": cid,
        "selection_revision": 1,
        "playhead_s": 0,
        "playing": False,
        "busy": False,
        "ready": True,
    }
    service.poll({"session_id": sid, "state": state})
    return client, db, service, sid, state, dict(origin, Authorization="Bearer " + key)


def command(service, sid, state, properties=None, kind="set_clip_properties", cid=None):
    result = {
        "command_id": cid or secrets.token_hex(8),
        "type": kind,
        "session_id": sid,
        "project_id": state["project_id"],
        "clip_id": state["clip_id"],
        "expected_state_token": service.editor_state()["state_token"],
        "expires_at": time.time() + 20,
    }
    if kind == "set_clip_properties":
        result["properties"] = properties or {"contrast": 15}
    elif kind == "undo_last_change":
        result["undo_command_id"] = (
            service.latest_external.command_id
            if service.latest_external
            else "no-external-command"
        )
    return result


def execute(service, sid, state, cmd):
    service.submit(cmd)
    return service.execute(
        {"session_id": sid, "state": state, "command_id": cmd["command_id"]}
    )


def raw(db, pid, cid):
    return next(c.effect_settings for c in db.list_studio_items(pid) if c.id == cid)


def test_original_preview_has_no_editable_target_and_rejects_old_write_and_undo(control):
    client, db, service, sid, state, headers = control
    edit = command(service, sid, state)
    assert execute(service, sid, state, edit)["persisted"]
    old_write = command(service, sid, state, cid="before-original-write")
    old_undo = command(
        service, sid, state, kind="undo_last_change", cid="before-original-undo"
    )
    queued = command(service, sid, state, cid="queued-before-original")
    service.submit(queued)
    before = raw(db, state["project_id"], state["clip_id"])
    draft_state = dict(
        state, clip_id=None, ready=False, selection_revision=state["selection_revision"] + 1
    )
    polled = client.post(
        "/api/studio/control/poll",
        json={"session_id": sid, "state": draft_state},
        headers=headers,
    )
    assert polled.status_code == 200
    observed = client.get("/api/control/v1/editor-state", headers=headers).json()
    assert observed["clip_id"] is None
    assert observed["ready"] is False
    assert observed["properties"] is None
    executed = client.post(
        "/api/studio/control/execute",
        json={"session_id": sid, "state": draft_state, "command_id": queued["command_id"]},
        headers=headers,
    ).json()
    assert executed["persisted"] is False
    assert executed["error_code"] == "STALE_SELECTION"
    for stale in (old_write, old_undo):
        rejected = client.post(
            "/api/control/v1/commands", json=stale, headers=headers
        )
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "STALE_SELECTION"
    assert raw(db, state["project_id"], state["clip_id"]) == before


def test_combined_update_history_redo_and_preservation(control, tmp_path):
    client, db, service, sid, state, headers = control
    cid, pid = state["clip_id"], state["project_id"]
    existing = {
        "frame": {"zoom": 1.2},
        "color": {"input_profile": "rec709", "future_field": "keep"},
        "image": {"exposure": 8, "warmth": 10},
    }
    with db.connect() as conn:
        conn.execute(
            "UPDATE studio_clips SET effect_settings=? WHERE id=?",
            (json.dumps(existing), cid),
        )
    from orga_drone.lut_library import import_lut_bytes

    cube = b"LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n"
    lut = import_lut_bytes(
        db, service.data_dir, cube, source_label="test.cube"
    ).entry.asset_name
    before = raw(db, pid, cid)
    cmd = command(
        service,
        sid,
        state,
        {
            "contrast": 15,
            "saturation_percent": 120,
            "creative_lut_id": lut,
            "creative_lut_strength_percent": 100,
        },
    )
    result = execute(service, sid, state, cmd)
    assert result["persisted"], result
    stored = json.loads(raw(db, pid, cid))
    assert stored["image"]["saturation"] == 20
    assert stored["image"]["exposure"] == 8
    assert stored["color"]["future_field"] == "keep"
    assert stored["frame"] == existing["frame"]
    assert service.submit(cmd)["persisted"]
    assert service.result(cmd["command_id"])["status"] == "persisted_ui_unconfirmed"
    ack = service.acknowledge(
        {
            "session_id": sid,
            "command_id": cmd["command_id"],
            "preview_status": "refresh_requested",
        }
    )
    assert ack["ui_applied"] and ack["preview_status"] == "refresh_requested"
    undo = command(service, sid, state, kind="undo_last_change")
    assert execute(service, sid, state, undo)["persisted"]
    assert raw(db, pid, cid) == before
    assert not history_flags(pid)["can_undo"]  # Exactly one external step.
    assert redo_story(db, pid)
    assert json.loads(raw(db, pid, cid))["image"]["contrast"] == 15
    assert (
        client.get("/api/control/v1/editor-state", headers=headers).status_code == 200
    )
    assert (tmp_path / "media/synthetic.MP4").read_bytes().startswith(b"media-bytes-")


@pytest.mark.parametrize(
    "patch",
    [
        {"contrast": True},
        {"contrast": 101},
        {"contrast": 1.5},
        {"saturation_percent": -1},
        {"saturation_percent": 201},
        {"creative_lut_strength_percent": 101},
        {"creative_lut_id": "../../x.cube"},
        {"unknown": 1},
    ],
)
def test_invalid_properties(control, patch):
    _, _, service, sid, state, _ = control
    with pytest.raises(ControlError):
        service.submit(command(service, sid, state, patch))


def test_noop_missing_lut_and_atomic_failure(control, monkeypatch):
    _, db, service, sid, state, _ = control
    before = raw(db, state["project_id"], state["clip_id"])
    no_op = execute(service, sid, state, command(service, sid, state, {"contrast": 0}))
    assert no_op["no_op"] and not history_flags(state["project_id"])["can_undo"]
    missing = execute(
        service,
        sid,
        state,
        command(
            service, sid, state, {"contrast": 15, "creative_lut_id": "a" * 32 + ".cube"}
        ),
    )
    assert missing["error_code"] == "LUT_UNAVAILABLE"
    assert raw(db, state["project_id"], state["clip_id"]) == before
    cmd = command(service, sid, state)
    service.submit(cmd)
    import orga_drone.studio_history as history

    original = history._capture_story
    calls = 0

    def fail_after(conn, project):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic snapshot failure")
        return original(conn, project)

    monkeypatch.setattr(history, "_capture_story", fail_after)
    result = service.execute(
        {"session_id": sid, "state": state, "command_id": cmd["command_id"]}
    )
    assert result["error_code"] == "DATABASE_ERROR"
    assert raw(db, state["project_id"], state["clip_id"]) == before
    assert not history_flags(state["project_id"])["can_undo"]


def test_selection_revision_pending_expiry_and_id_conflict(control):
    _, _, service, sid, state, _ = control
    cmd = command(service, sid, state)
    service.submit(cmd)
    changed = dict(state, selection_revision=3)  # A -> B -> A between polls.
    result = service.execute(
        {"session_id": sid, "state": changed, "command_id": cmd["command_id"]}
    )
    assert result["error_code"] == "STALE_STATE"
    with pytest.raises(ControlError) as exc:
        service.submit(dict(cmd, properties={"contrast": 2}))
    assert exc.value.code == "COMMAND_ID_CONFLICT"
    busy = dict(state, busy=True)
    service.poll({"session_id": sid, "state": busy})
    with pytest.raises(ControlError) as exc:
        service.submit(command(service, sid, state))
    assert exc.value.code == "EDITOR_BUSY"
    service.poll({"session_id": sid, "state": state})
    cmd = command(service, sid, state)
    service.submit(cmd)
    service.clock = lambda: time.monotonic() + 31
    assert service.result(cmd["command_id"])["error_code"] == "COMMAND_EXPIRED"
    with pytest.raises(ControlError) as exc:
        service.editor_state()
    assert exc.value.code == "EDITOR_DISCONNECTED"


def test_human_edit_blocks_guarded_undo(control):
    client, db, service, sid, state, headers = control
    assert execute(service, sid, state, command(service, sid, state))["persisted"]
    response = client.patch(
        f"/api/studio/{state['clip_id']}/image", json={"warmth": 12}, headers=headers
    )
    assert response.status_code == 200
    with pytest.raises(ControlError) as exc:
        service.submit(command(service, sid, state, kind="undo_last_change"))
    assert exc.value.code == "UNDO_CONFLICT"
    assert (
        json.loads(raw(db, state["project_id"], state["clip_id"]))["image"]["warmth"]
        == 12
    )


def test_security_lifecycle_and_payloads(control):
    client, db, service, sid, state, headers = control
    url = "/api/control/v1/editor-state"
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert (
        client.get(url, headers=dict(headers, Host="evil.example")).status_code == 403
    )
    assert (
        client.get(url, headers=dict(headers, Origin="http://evil.example")).status_code
        == 403
    )
    assert (
        client.post(
            "/api/control/v1/commands", content="{", headers=headers
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/control/v1/commands", content='"' + "x" * 9000 + '"', headers=headers
        ).status_code
        == 413
    )
    assert (
        client.post(
            "/api/studio/control/disable",
            json={},
            headers={"Origin": "http://evil.example"},
        ).status_code
        == 403
    )
    with pytest.raises(ControlError) as exc:
        service.poll({"session_id": "other", "state": state})
    assert exc.value.code == "EDITOR_SESSION_CONFLICT"
    cmd = command(service, sid, state)
    service.submit(cmd)
    service.disable()
    assert service.result(cmd["command_id"])["error_code"] == "CONTROL_DISABLED"
    assert client.get(url, headers=headers).status_code == 403
    restarted = ControlService(db, service.data_dir)
    assert not restarted.enabled and restarted.instance != service.instance
    assert not restarted.commands


@pytest.mark.parametrize(
    "field,value", [("item_kind", "title_card"), ("kind_snapshot", "photo")]
)
def test_unsupported_clip(control, field, value):
    _, db, service, sid, state, _ = control
    with db.connect() as conn:
        if field == "item_kind":
            conn.execute(
                "UPDATE studio_clips SET item_kind='title_card', media_path=NULL, identity_key=NULL, source_media_id=NULL WHERE id=?",
                (state["clip_id"],),
            )
        else:
            conn.execute(
                f"UPDATE studio_clips SET {field}=? WHERE id=?",
                (value, state["clip_id"]),
            )
        if field == "kind_snapshot":
            conn.execute("UPDATE media SET kind='photo'")
    with pytest.raises(ControlError) as exc:
        service.submit(command(service, sid, state))
    assert exc.value.code == "UNSUPPORTED_CLIP"


def test_animated_missing_media_and_unknown_command(control):
    _, db, service, sid, state, _ = control
    cmd = command(service, sid, state)
    with pytest.raises(ControlError) as exc:
        service.submit(dict(cmd, type="export"))
    assert exc.value.code == "UNKNOWN_COMMAND"
    with db.connect() as conn:
        conn.execute(
            "UPDATE studio_clips SET effect_settings=? WHERE id=?",
            ('{"saturation_ramp":{"enabled":true}}', state["clip_id"]),
        )
    with pytest.raises(ControlError) as exc:
        service.submit(command(service, sid, state))
    assert exc.value.code == "ANIMATED_SETTINGS_UNSUPPORTED"
    with db.connect() as conn:
        conn.execute("UPDATE studio_clips SET effect_settings='{}'")
    Path(db.list_studio_items()[0].media_path).unlink()  # Synthetic fixture only.
    with pytest.raises(ControlError) as exc:
        service.submit(command(service, sid, state))
    assert exc.value.code == "MEDIA_UNAVAILABLE"


@pytest.mark.parametrize("failure", ["write", "commit"])
def test_write_and_commit_failure_preserve_history_and_settings(
    control, monkeypatch, failure
):
    _, db, service, sid, state, _ = control
    before = raw(db, state["project_id"], state["clip_id"])
    cmd = command(service, sid, state)
    service.submit(cmd)
    original = db.connect

    @contextmanager
    def injected():
        with original() as conn:
            if failure == "write":
                conn.execute(
                    "CREATE TEMP TRIGGER deny_update BEFORE UPDATE ON studio_clips BEGIN SELECT RAISE(ABORT, 'synthetic'); END"
                )
            yield conn
            if failure == "commit" and conn.in_transaction:
                raise RuntimeError("synthetic commit failure")

    monkeypatch.setattr(db, "connect", injected)
    result = service.execute(
        {"session_id": sid, "state": state, "command_id": cmd["command_id"]}
    )
    assert result["error_code"] == "DATABASE_ERROR"
    monkeypatch.setattr(db, "connect", original)
    assert raw(db, state["project_id"], state["clip_id"]) == before
    assert not history_flags(state["project_id"])["can_undo"]


def test_full_http_handshake_and_secret_not_rendered(control):
    client, _, service, sid, state, headers = control
    cmd = command(service, sid, state)
    response = client.post("/api/control/v1/commands", json=cmd, headers=headers)
    assert response.status_code == 200 and response.json()["status"] == "queued"
    poll = client.post(
        "/api/studio/control/poll", json={"session_id": sid, "state": state}
    )
    assert poll.json()["commands"][0]["command_id"] == cmd["command_id"]
    result = client.post(
        "/api/studio/control/execute",
        json={"session_id": sid, "state": state, "command_id": cmd["command_id"]},
    )
    assert result.json()["persisted"]
    status = client.get(
        "/api/control/v1/commands/" + cmd["command_id"], headers=headers
    )
    assert status.json()["status"] == "persisted_ui_unconfirmed"
    ack = client.post(
        "/api/studio/control/ack",
        json={
            "session_id": sid,
            "command_id": cmd["command_id"],
            "preview_status": "refresh_requested",
        },
    )
    assert ack.json()["ui_applied"]
    page = client.get("/studio").text
    assert "studio-control-key" in page
    assert headers["Authorization"][7:] not in page + str(status.json())
    controls = client.get("/api/control/v1/available-controls", headers=headers)
    assert controls.json()["controls"]["saturation_percent"]["maximum"] == 200


@pytest.mark.parametrize(
    "endpoint,payload", [("hud", {"enabled": False}), ("map", {"enabled": False})]
)
def test_human_non_image_edits_invalidate_undo(control, endpoint, payload):
    client, _, service, sid, state, headers = control
    assert execute(service, sid, state, command(service, sid, state))["persisted"]
    response = client.patch(
        f"/api/studio/{state['clip_id']}/{endpoint}", json=payload, headers=headers
    )
    assert response.status_code == 200
    with pytest.raises(ControlError) as exc:
        service.submit(command(service, sid, state, kind="undo_last_change"))
    assert exc.value.code == "UNDO_CONFLICT"


def test_stale_project_and_session_restart_and_unsupported_bridge(control):
    client, db, service, sid, state, headers = control
    cmd = command(service, sid, state)
    service.submit(cmd)
    with db.connect() as conn:
        conn.execute(
            "UPDATE studio_projects SET title='synthetic change' WHERE id=?",
            (state["project_id"],),
        )
    result = service.execute(
        {"session_id": sid, "state": state, "command_id": cmd["command_id"]}
    )
    assert result["error_code"] == "STALE_STATE"
    assert client.post("/api/studio/control/export", json={}).status_code == 404
    with pytest.raises(ControlError) as exc:
        service.execute(
            {"session_id": "other", "state": state, "command_id": cmd["command_id"]}
        )
    assert exc.value.code == "EDITOR_SESSION_CONFLICT"
    prior_token = service.editor_state()["state_token"]
    service.instance = "synthetic-restarted-instance"
    assert service.editor_state()["state_token"] != prior_token


def test_nonloopback_bind_and_peer_rejected(control):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from orga_drone.control_routes import control_router

    _, _, service, sid, state, _ = control
    for bind, peer in [("0.0.0.0", "127.0.0.1"), ("127.0.0.1", "192.0.2.1")]:
        app = FastAPI()
        app.include_router(control_router(service, bind))
        with pytest.raises(ControlError) as exc:
            TestClient(app, client=(peer, 50000)).get("/api/control/v1/editor-state")
        assert exc.value.code == "LOOPBACK_REQUIRED"


def test_lost_ack_does_not_overwrite_later_human_edit(control):
    client, _, service, sid, state, headers = control
    cmd = command(service, sid, state)
    assert execute(service, sid, state, cmd)["persisted"]
    client.patch(
        f"/api/studio/{state['clip_id']}/image", json={"contrast": 9}, headers=headers
    )
    polled = service.poll({"session_id": sid, "state": state})
    assert not polled["commands"]
    assert service.result(cmd["command_id"])["persisted"]
    assert not service.result(cmd["command_id"])["ui_applied"]


def test_committed_outcome_readable_after_editor_disconnect(control):
    client, _, service, sid, state, headers = control
    cmd = command(service, sid, state)
    assert execute(service, sid, state, cmd)["persisted"]
    service.clock = lambda: time.monotonic() + 5
    result = client.get(
        "/api/control/v1/commands/" + cmd["command_id"], headers=headers
    )
    assert result.status_code == 200
    assert result.json()["status"] == "persisted_ui_unconfirmed"
    assert service.submit(cmd)["persisted"]


def test_two_clip_undo_binds_original_project_clip_and_command(control, tmp_path):
    from orga_drone.studio_history import history_revision

    client, db, service, sid, state_a, headers = control
    pid, clip_a = state_a["project_id"], state_a["clip_id"]
    clip_b = _seed(db, tmp_path / "second-media", "B.MP4", 10, project_id=pid)
    before_a, before_b = raw(db, pid, clip_a), raw(db, pid, clip_b)
    edit = command(service, sid, state_a, {"contrast": 15, "saturation_percent": 120})
    assert execute(service, sid, state_a, edit)["persisted"]
    changed_a = raw(db, pid, clip_a)
    revision = history_revision()
    flags = history_flags(pid)

    state_b = dict(state_a, clip_id=clip_b, selection_revision=2)
    service.poll({"session_id": sid, "state": state_b})
    wrong_clip_undo = command(service, sid, state_b, kind="undo_last_change")
    assert wrong_clip_undo["undo_command_id"] == edit["command_id"]
    with pytest.raises(ControlError) as exc:
        service.submit(wrong_clip_undo)
    assert exc.value.code == "UNDO_CONFLICT"
    assert raw(db, pid, clip_a) == changed_a
    assert raw(db, pid, clip_b) == before_b
    assert history_revision() == revision and history_flags(pid) == flags

    selected_a = dict(state_a, selection_revision=3)
    service.poll({"session_id": sid, "state": selected_a})
    wrong_operation = command(service, sid, selected_a, kind="undo_last_change")
    wrong_operation["undo_command_id"] = "different-operation"
    with pytest.raises(ControlError) as exc:
        service.submit(wrong_operation)
    assert exc.value.code == "UNDO_CONFLICT"
    assert raw(db, pid, clip_a) == changed_a and history_revision() == revision

    undo = command(service, sid, selected_a, kind="undo_last_change")
    result = execute(service, sid, selected_a, undo)
    assert result["persisted"] and result["clip_id"] == clip_a
    assert (
        result["project_id"] == pid
        and result["undone_command_id"] == edit["command_id"]
    )
    assert result["canonical"]["image"]["contrast"] == 0
    assert raw(db, pid, clip_a) == before_a and raw(db, pid, clip_b) == before_b
    revision = history_revision()
    assert service.submit(undo)["persisted"]  # No second Undo on duplicate ID.
    assert history_revision() == revision and history_flags(pid)["can_redo"]

    # Ordinary Redo uses the existing route and reloads the canonical Studio page.
    response = client.post("/api/studio/history/redo", headers=headers)
    assert response.status_code == 200
    assert raw(db, pid, clip_a) == changed_a and raw(db, pid, clip_b) == before_b
    from html.parser import HTMLParser

    class ClipDatasets(HTMLParser):
        def __init__(self):
            super().__init__()
            self.images = {}

        def handle_starttag(self, tag, attrs):
            data = dict(attrs)
            if "data-image-adjust" in data:
                self.images[int(data["data-studio-id"])] = json.loads(
                    data["data-image-adjust"]
                )

    rendered = ClipDatasets()
    rendered.feed(client.get("/studio").text)
    assert rendered.images[clip_a]["contrast"] == 15
    assert rendered.images[clip_a]["saturation"] == 20
    assert rendered.images[clip_b]["contrast"] == 0


def test_undo_requires_original_command_and_rechecks_target_at_execution(control):
    _, db, service, sid, state, _ = control
    edit = command(service, sid, state)
    assert execute(service, sid, state, edit)["persisted"]
    undo = command(service, sid, state, kind="undo_last_change")
    missing = dict(undo)
    del missing["undo_command_id"]
    with pytest.raises(ControlError) as exc:
        service.submit(missing)
    assert exc.value.code == "INVALID_PAYLOAD"
    service.submit(undo)
    # Even a fresh admission cannot bypass the final target check.
    result = service.execute(
        {
            "session_id": sid,
            "command_id": undo["command_id"],
            "state": dict(state, clip_id=state["clip_id"] + 1, selection_revision=2),
        }
    )
    assert result["error_code"] == "STALE_SELECTION"
    assert (
        json.loads(raw(db, state["project_id"], state["clip_id"]))["image"]["contrast"]
        == 15
    )


@pytest.mark.parametrize("field", ["expires_at", "project_id", "clip_id"])
def test_http_huge_command_numbers_return_stable_errors(control, field):
    client, _, service, sid, state, headers = control
    payload = command(service, sid, state)
    payload[field] = 10**400
    response = client.post("/api/control/v1/commands", json=payload, headers=headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] in {"INVALID_PAYLOAD", "INVALID_IDENTIFIER"}


@pytest.mark.parametrize(
    "field", ["playhead_s", "selection_revision", "project_id", "clip_id"]
)
def test_http_huge_bridge_numbers_return_stable_errors(control, field):
    client, _, _, sid, state, _ = control
    payload = {"session_id": sid, "state": dict(state, **{field: 10**400})}
    response = client.post("/api/studio/control/poll", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] in {"INVALID_PAYLOAD", "INVALID_IDENTIFIER"}


@pytest.mark.parametrize("depth", [1500, 4000])
def test_http_deep_json_returns_stable_error(control, depth):
    client, _, _, _, _, headers = control
    response = client.post(
        "/api/control/v1/commands",
        content="[" * depth + "0" + "]" * depth,
        headers=headers,
    )
    assert response.status_code == 400
    # A parser may accept this valid array or reach its recursion limit first.
    assert response.json()["error"]["code"] in {"INVALID_JSON", "INVALID_PAYLOAD"}


@pytest.mark.parametrize(
    "foreign", [{"Origin": "http://evil.example"}, {"Host": "evil.example"}]
)
def test_rejected_requests_preserve_token_and_guarded_undo(control, foreign):
    from orga_drone.studio_history import history_revision

    client, _, service, sid, state, _ = control
    edit = command(service, sid, state)
    assert execute(service, sid, state, edit)["persisted"]
    token = service.editor_state()["state_token"]
    revision = history_revision()
    response = client.post(
        "/api/studio/reorder", json={"ids": [state["clip_id"]]}, headers=foreign
    )
    assert response.status_code == 403
    assert history_revision() == revision
    assert service.editor_state()["state_token"] == token
    undo = command(service, sid, state, kind="undo_last_change")
    assert execute(service, sid, state, undo)["persisted"]


def test_action_discovery_is_versioned_and_authenticated(control):
    client, _, _, _, _, headers = control
    actions = client.get("/api/control/v1/actions", headers=headers)
    assert actions.status_code == 200
    payload = actions.json()
    assert payload["contract_version"] == 1
    assert payload["actions"][0]["name"] == "clip.color.properties"
    controls = client.get("/api/control/v1/available-controls", headers=headers)
    assert controls.json()["contract_version"] == 1
    assert controls.json()["actions"] == payload["actions"]
    assert client.get("/api/control/v1/actions").status_code == 401


def test_control_and_ui_use_the_same_color_domain_result(control, tmp_path):
    client, db, service, sid, state, headers = control
    pid = state["project_id"]
    clip_b = _seed(db, tmp_path / "second-media", "B.MP4", 10, project_id=pid)
    edit = command(
        service,
        sid,
        state,
        {"contrast": 15, "saturation_percent": 120},
    )
    assert execute(service, sid, state, edit)["persisted"]
    response = client.patch(
        f"/api/studio/{clip_b}/image",
        json={"contrast": 15, "saturation": 20},
        headers=headers,
    )
    assert response.status_code == 200
    stored_a = json.loads(raw(db, pid, state["clip_id"]))
    stored_b = json.loads(raw(db, pid, clip_b))
    assert stored_a["image"] == stored_b["image"]
