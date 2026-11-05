"""Synthetic project lifecycle, lease, transaction and UI/API parity contracts."""

from __future__ import annotations

import secrets
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

from orga_drone.control import ControlError
from orga_drone.db import Database
from orga_drone.project_actions import create_project
from orga_drone.studio_history import history_flags

pytest_plugins = ["tests.test_control_api"]


@pytest.fixture
def projects(control):
    client, db, service, sid, state, headers = control
    db.set_open_studio_project_id(state["project_id"])
    service.poll({"session_id": sid, "state": state})
    return control


def project_command(service, sid, state, action, params=None):
    return {
        "command_id": secrets.token_hex(8),
        "type": "project_action",
        "session_id": sid,
        "project_id": state["project_id"],
        "clip_id": None,
        "expected_state_token": service.editor_state()["state_token"],
        "expires_at": time.time() + 20,
        "action": action,
        "action_version": 1,
        "params": params or {},
    }


def run(service, sid, state, cmd):
    service.submit(cmd)
    return service.execute(
        {"session_id": sid, "state": state, "command_id": cmd["command_id"]}
    )


def test_create_open_reopen_preserves_existing_format_and_fences_old_editor(projects):
    client, db, service, sid, state, headers = projects
    before = db.list_studio_projects()
    cmd = project_command(service, sid, state, "project.create", {"title": "New story"})
    result = run(service, sid, state, cmd)
    assert result["persisted"] and result["navigation_required"]
    assert not result["ui_applied"] and result["clip_id"] is None
    pid = result["canonical"]["project"]["id"]
    assert pid != state["project_id"]
    assert db.get_open_studio_project().id == pid
    assert len(db.list_studio_projects()) == len(before) + 1
    assert Database(db.path).get_open_studio_project().id == pid
    assert service.submit(cmd)["persisted"]  # exact idempotent replay
    retired = dict(service.session)
    recovered = service.poll({"session_id": sid, "state": state})
    assert recovered["commands"][0]["persisted"]
    assert service.session == retired  # old poll cannot revive project/lease/state
    with pytest.raises(ControlError, match="STALE_STATE"):
        service.editor_state()
    ack = service.acknowledge(
        {
            "session_id": sid,
            "command_id": cmd["command_id"],
            "preview_status": "unavailable",
        }
    )
    assert ack["persisted"] and not ack["ui_applied"]
    assert client.get("/studio").status_code == 200


def test_rename_empty_or_photo_project_does_not_require_editable_video(projects):
    client, db, service, sid, state, headers = projects
    empty = create_project(db, "Empty", open_created=True)
    state = dict(state, project_id=empty.id, clip_id=None, ready=False)
    service.poll({"session_id": sid, "state": state})
    cmd = project_command(
        service, sid, state, "project.rename", {"title": "Persisted title"}
    )
    result = run(service, sid, state, cmd)
    assert result["persisted"] and not result["navigation_required"]
    assert Database(db.path).get_studio_project(empty.id).title == "Persisted title"
    assert history_flags(empty.id) == {"can_undo": False, "can_redo": False}
    assert service.acknowledge(
        {
            "session_id": sid,
            "command_id": cmd["command_id"],
            "preview_status": "unavailable",
        }
    )["ui_applied"]


def test_open_destination_is_explicit_and_pending_writes_are_rejected(projects):
    client, db, service, sid, state, headers = projects
    other = create_project(db, "Other")
    cmd = project_command(service, sid, state, "project.open", {"project_id": other.id})
    pending = project_command(service, sid, state, "project.rename", {"title": "Wrong"})
    service.submit(pending)
    result = run(service, sid, state, cmd)
    assert result["persisted"]
    assert db.get_open_studio_project().id == other.id
    assert service.external_result(pending["command_id"])["error_code"] == "STALE_STATE"
    assert db.get_studio_project(state["project_id"]).title != "Wrong"


def test_delete_only_project_references_preserves_source_and_other_project(projects):
    client, db, service, sid, state, headers = projects
    other = create_project(db, "Keep")
    media = db.list_media()[0]
    from pathlib import Path

    source = Path(media.path)
    before = source.read_bytes()
    result = run(
        service, sid, state, project_command(service, sid, state, "project.delete")
    )
    assert result["persisted"] and result["canonical"]["project"] is None
    assert db.get_studio_project(state["project_id"]) is None
    assert db.get_studio_project(other.id) is not None
    assert db.get_open_studio_project() is None
    assert source.read_bytes() == before and db.get_media(media.id) is not None


@pytest.mark.parametrize(
    "change,error",
    [
        ({"session_id": "wrong"}, "EDITOR_SESSION_CONFLICT"),
        ({"project_id": 99999}, "STALE_SELECTION"),
        ({"clip_id": 1}, "INVALID_TARGET"),
        ({"expected_state_token": "0" * 64}, "STALE_STATE"),
        ({"action_version": 99}, "UNKNOWN_ACTION"),
        ({"params": {"title": ""}}, "INVALID_PARAMS"),
    ],
)
def test_invalid_project_context_is_rejected(projects, change, error):
    client, db, service, sid, state, headers = projects
    cmd = project_command(service, sid, state, "project.rename", {"title": "Never"})
    cmd.update(change)
    with pytest.raises(ControlError, match=error):
        service.submit(cmd)
    assert db.get_studio_project(state["project_id"]).title != "Never"


def test_concurrent_commands_with_same_token_commit_only_one(projects):
    client, db, service, sid, state, headers = projects
    cmds = [
        project_command(service, sid, state, "project.rename", {"title": title})
        for title in ["First", "Second"]
    ]
    for cmd in cmds:
        service.submit(cmd)

    def execute(cmd):
        return service.execute(
            {"session_id": sid, "state": state, "command_id": cmd["command_id"]}
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, cmds))
    assert sum(bool(r["persisted"]) for r in results) == 1
    assert [r["error_code"] for r in results if not r["persisted"]] == ["STALE_STATE"]


def test_open_project_changed_before_poll_rejects_wrong_context(projects):
    client, db, service, sid, state, headers = projects
    cmd = project_command(service, sid, state, "project.rename", {"title": "Never"})
    service.submit(cmd)
    other = create_project(db, "Other", open_created=True)
    result = service.execute(
        {"session_id": sid, "state": state, "command_id": cmd["command_id"]}
    )
    assert not result["persisted"] and result["error_code"] == "STALE_STATE"
    assert db.get_open_studio_project().id == other.id


def test_commit_failure_rolls_back_created_project_and_open_context(
    projects, monkeypatch
):
    client, db, service, sid, state, headers = projects
    cmd = project_command(service, sid, state, "project.create", {"title": "Rollback"})
    service.submit(cmd)
    before = db.list_studio_projects()
    original = db.connect

    @contextmanager
    def fail_commit():
        with original() as conn:
            yield conn
            if conn.in_transaction:
                raise sqlite3.OperationalError("synthetic commit failure")

    monkeypatch.setattr(db, "connect", fail_commit)
    result = service.execute(
        {"session_id": sid, "state": state, "command_id": cmd["command_id"]}
    )
    monkeypatch.setattr(db, "connect", original)
    assert not result["persisted"] and result["error_code"] == "DATABASE_ERROR"
    assert db.list_studio_projects() == before
    assert db.get_open_studio_project().id == state["project_id"]
    assert not service.session.get("fenced")


def test_project_reads_are_path_free_and_match_existing_ui(projects):
    client, db, service, sid, state, headers = projects
    payload = {
        "session_id": sid,
        "action": "project.list",
        "action_version": 1,
        "target": {},
        "params": {},
    }
    response = client.post(
        "/api/control/v1/read-actions", json=payload, headers=headers
    )
    assert response.status_code == 200
    view = response.json()["result"]
    assert view["projects"] == client.get("/api/studio/projects").json()["projects"]
    payload.update(action="project.get", target={"project_id": state["project_id"]})
    detail = client.post("/api/control/v1/read-actions", json=payload, headers=headers)
    assert detail.status_code == 200 and detail.json()["result"]["clips"]
    assert "media_path" not in detail.text and str(db.path.parent) not in detail.text
    payload["target"] = {"project_id": 99999}
    assert (
        client.post(
            "/api/control/v1/read-actions", json=payload, headers=headers
        ).json()["error"]["code"]
        == "TARGET_NOT_FOUND"
    )
    payload["target"] = {"project_id": True}
    assert (
        client.post(
            "/api/control/v1/read-actions", json=payload, headers=headers
        ).status_code
        == 400
    )


def test_ui_create_only_and_form_create_open_share_implementation(projects):
    client, db, service, sid, state, headers = projects
    result = client.post(
        "/api/studio/projects", json={"title": "Created only"}, headers=headers
    )
    assert result.status_code == 201
    assert db.get_open_studio_project().id == state["project_id"]
    assert (
        client.post(
            "/studio/projects", headers=headers, follow_redirects=False
        ).status_code
        == 303
    )
    assert db.get_open_studio_project().id != state["project_id"]


def test_rename_reports_retained_story_history_and_cannot_undo_other_project(projects):
    client, db, service, sid, state, headers = projects
    from tests.test_control_api import command, execute

    color = command(service, sid, state)
    assert execute(service, sid, state, color)["persisted"]
    before = history_flags(state["project_id"])
    assert before["can_undo"]
    result = run(
        service,
        sid,
        state,
        project_command(service, sid, state, "project.rename", {"title": "Keep undo"}),
    )
    assert result["persisted"]
    assert {key: result[key] for key in before} == before
    assert history_flags(state["project_id"]) == before
    undo = command(service, sid, state, kind="undo_last_change")
    with pytest.raises(ControlError, match="UNDO_CONFLICT"):
        service.submit(undo)


def test_lease_expiring_after_write_rolls_back_before_commit(projects, monkeypatch):
    client, db, service, sid, state, headers = projects
    before = db.list_studio_projects()
    now = service.clock()
    original = db.create_studio_project

    def expire_after_write(*args, **kwargs):
        result = original(*args, **kwargs)
        service.clock = lambda: now + 4
        return result

    cmd = project_command(
        service, sid, state, "project.create", {"title": "Never committed"}
    )
    service.submit(cmd)
    monkeypatch.setattr(db, "create_studio_project", expire_after_write)
    result = service.execute(
        {"session_id": sid, "state": state, "command_id": cmd["command_id"]}
    )
    assert not result["persisted"] and result["error_code"] == "EDITOR_DISCONNECTED"
    assert db.list_studio_projects() == before
    assert db.get_open_studio_project().id == state["project_id"]


def test_state_changed_between_admission_check_and_write_transaction_is_rejected(
    projects, monkeypatch
):
    client, db, service, sid, state, headers = projects
    cmd = project_command(service, sid, state, "project.rename", {"title": "Never"})
    service.submit(cmd)
    original = db.get_open_studio_project

    def concurrent_change():
        project = original()
        with db.connect() as conn:
            conn.execute(
                "UPDATE studio_projects SET title = ? WHERE id = ?",
                ("Concurrent local edit", state["project_id"]),
            )
        return project

    monkeypatch.setattr(db, "get_open_studio_project", concurrent_change)
    result = service.execute(
        {"session_id": sid, "state": state, "command_id": cmd["command_id"]}
    )
    assert not result["persisted"] and result["error_code"] == "STALE_STATE"
    assert db.get_studio_project(state["project_id"]).title == "Concurrent local edit"


def test_shared_ui_create_open_rolls_back_when_open_persistence_fails(
    projects, monkeypatch
):
    client, db, service, sid, state, headers = projects
    before = db.list_studio_projects()

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic app_state persistence failure")

    monkeypatch.setattr(db, "set_open_studio_project_id", fail)
    with pytest.raises(sqlite3.OperationalError):
        create_project(db, "Rollback UI", open_created=True)
    assert db.list_studio_projects() == before
    assert db.get_open_studio_project().id == state["project_id"]


def test_unknown_destination_and_wrong_action_scope_are_rejected(projects):
    client, db, service, sid, state, headers = projects
    cmd = project_command(service, sid, state, "project.open", {"project_id": 99999})
    result = run(service, sid, state, cmd)
    assert not result["persisted"] and result["error_code"] == "TARGET_NOT_FOUND"
    for action, params in [
        ("project.list", {}),
        ("library.media.list", {}),
        ("clip.color.image", {"contrast": 1}),
    ]:
        cmd = project_command(service, sid, state, action, params)
        with pytest.raises(ControlError, match="INVALID_ACTION_SCOPE"):
            service.submit(cmd)
    cmd = project_command(service, sid, state, "project.rename", {"title": "No"})
    cmd.update(type="apply_action", clip_id=state["clip_id"])
    with pytest.raises(ControlError, match="INVALID_ACTION_SCOPE"):
        service.submit(cmd)


def test_retired_session_poll_recovers_committed_navigation_after_lease_expiry(
    projects,
):
    client, db, service, sid, state, headers = projects
    cmd = project_command(service, sid, state, "project.create", {"title": "Committed"})
    assert run(service, sid, state, cmd)["persisted"]
    saved = dict(service.session)
    service.clock = lambda: saved["seen"] + 30
    stale = dict(state, project_id=99999, clip_id=None, selection_revision=0)
    recovered = service.poll({"session_id": sid, "state": stale})
    assert len(recovered["commands"]) == 1
    assert recovered["commands"][0]["navigation_required"]
    assert recovered["commands"][0]["persisted"]
    assert service.session == saved
    with pytest.raises(
        ControlError, match="EDITOR_SESSION_CONFLICT|EDITOR_DISCONNECTED"
    ):
        service.poll({"session_id": "other-window", "state": stale})


def test_bridge_recovery_is_read_only_session_owned_and_survives_lease_expiry(projects):
    client, db, service, sid, state, headers = projects
    cmd = project_command(service, sid, state, "project.open", {"project_id": 99999})
    rejected = run(service, sid, state, cmd)
    session = dict(service.session)
    service.clock = lambda: session["seen"] + 30
    result = client.post(
        "/api/studio/control/recover",
        headers=headers,
        json={"session_id": sid, "command_id": cmd["command_id"]},
    )
    assert result.status_code == 200
    assert result.json() == rejected
    assert service.session == session
    with pytest.raises(ControlError, match="EDITOR_SESSION_CONFLICT"):
        service.recover(
            {"session_id": "another-editor", "command_id": cmd["command_id"]}
        )
    assert (
        client.post(
            "/api/studio/control/recover",
            headers={"Origin": "", "Sec-Fetch-Site": ""},
            json={"session_id": sid, "command_id": cmd["command_id"]},
        ).status_code
        == 403
    )
