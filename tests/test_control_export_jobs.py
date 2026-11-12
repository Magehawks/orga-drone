"""Export/render job commands through the Control API (issue #282).

export_start/export_status/export_cancel share the HTTP route's job store
and pipeline: same preflight validation (via ``prepare_studio_export``), same
single-active-export rule, same worker behavior. No silent overwrite is
possible (the field is rejected outright). Execute reports rejection in the
bridge result (status=rejected + error_code) without raising.
"""

from __future__ import annotations

import json
import secrets

from orga_drone.control import ControlError
import subprocess
import time

import pytest

from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from tests.test_studio_history import _client, _seed


def _run(*args: str) -> None:
    subprocess.run(
        [find_ffmpeg() or "ffmpeg", "-y", "-loglevel", "error", *args],
        check=True,
        capture_output=True,
        timeout=120,
        **subprocess_no_window_kwargs(),
    )


@pytest.fixture
def export_control(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """A Control session on a project with one real synthetic video clip."""
    client, db = _client(tmp_path, monkeypatch)
    _seed(db, tmp_path / "videos", "EXPORT.MP4", 2.0)
    # Real playable media for the render pipeline.
    media_file = tmp_path / "videos" / "EXPORT.MP4"
    _run(
        "-f", "lavfi", "-i", "color=c=blue:s=1280x720:r=30:d=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(media_file),
    )
    pid = db.list_studio_items()[0].project_id
    service = client.app.state.control  # type: ignore[attr-defined]
    key = secrets.token_hex(32)
    sid = "export-editor"
    assert (
        client.post(
            "/api/studio/control/enable",
            json={"session_id": sid, "pairing_key": key},
            headers={"Origin": "http://testserver"},
        ).status_code
        == 200
    )
    state = {
        "project_id": pid,
        "clip_id": db.list_studio_items()[0].id,
        "selection_revision": 1,
        "playhead_s": 0,
        "playing": True,  # exports must not require a paused editor
        "busy": False,
        "ready": True,
    }
    service.poll({"session_id": sid, "state": state})
    return client, db, service, sid, state, tmp_path


def _export_cmd(service, sid, state, *, kind="export_start", **extra):  # type: ignore[no-untyped-def]
    payload = {
        "command_id": secrets.token_hex(8),
        "type": kind,
        "session_id": sid,
        "project_id": state["project_id"],
        "clip_id": None,
        "expected_state_token": service.editor_state()["state_token"],
        "expires_at": time.time() + 20,
    }
    payload.update(extra)
    return payload


def _execute(service, sid, state, cmd):  # type: ignore[no-untyped-def]
    service.submit(cmd)
    return service.execute(
        {"session_id": sid, "state": state, "command_id": cmd["command_id"]}
    )


def _expect_rejected(service, sid, state, cmd, code: str) -> None:  # type: ignore[no-untyped-def]
    result = _execute(service, sid, state, cmd)
    assert result["status"] == "rejected", result
    assert result["error_code"] == code, result


def _wait_job(service, sid, state, job_id: str, timeout_s: float = 120) -> dict:  # type: ignore[no-untyped-def]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = _execute(service, sid, state, _export_cmd(
            service, sid, state, kind="export_status", job_id=job_id
        ))
        job = status["canonical"]["export_job"]
        if job["state"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.3)
    raise AssertionError("export job did not finish")


def _available_height(client, project_id: int) -> int:  # type: ignore[no-untyped-def]
    """The UI resolves export height from the project's source resolutions;
    the Control API follows the same rule (no upscaling)."""
    options = client.get(f"/api/studio/export/options?project_id={project_id}")
    assert options.status_code == 200, options.text
    resolutions = options.json().get("options") or []
    assert resolutions, options.text
    return int(resolutions[0]["height"])


def test_export_start_status_and_result(export_control, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Start, observe, and verify the rendered file — API and UI share the
    pipeline (the HTTP job route sees the same store)."""
    client, _db, service, sid, state, _tmp = export_control
    output = tmp_path / "control-export.mp4"
    started = _execute(service, sid, state, _export_cmd(
        service, sid, state,
        height=_available_height(client, state["project_id"]),
        output_path=str(output), quality="standard",
    ))
    assert started["status"] == "persisted", json.dumps(started, default=str)
    job_id = str(started["canonical"]["export_job_id"])
    job = _wait_job(service, sid, state, job_id)
    assert job["state"] == "completed", job
    assert job["output_path"] == str(output)
    assert output.is_file() and output.stat().st_size > 0
    # The HTTP route observes the same shared job.
    response = client.get(f"/api/studio/export/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["state"] == "completed"


def test_export_start_refuses_existing_file_without_overwrite(
    export_control, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """No silent overwrite: an existing output file stays untouched — the
    encoder claims a NEW variant name instead (identical to the HTTP route),
    and the overwrite field itself is rejected by the shape."""
    client, _db, service, sid, state, _tmp = export_control
    output = tmp_path / "exists.mp4"
    output.write_bytes(b"existing-bytes")
    started = _execute(service, sid, state, _export_cmd(
        service, sid, state,
        height=_available_height(client, state["project_id"]),
        output_path=str(output),
    ))
    assert started["status"] == "persisted", started
    job = _wait_job(service, sid, state, str(started["canonical"]["export_job_id"]))
    assert job["state"] == "completed", job
    # The existing file was never overwritten; the render landed on a
    # different claimed name.
    assert output.read_bytes() == b"existing-bytes"
    assert job["output_path"] != str(output)

    with pytest.raises(ControlError) as excinfo:
        _execute(service, sid, state, _export_cmd(
            service, sid, state, height=_available_height(client, state["project_id"]),
            output_path=str(tmp_path / "other.mp4"), overwrite=True,
        ))
    assert excinfo.value.code == "INVALID_PAYLOAD"

    with pytest.raises(ControlError) as excinfo:
        _execute(service, sid, state, _export_cmd(
            service, sid, state, height=_available_height(client, state["project_id"]),
            output_path=str(tmp_path / "other.mp4"), overwrite=True,
        ))
    assert excinfo.value.code == "INVALID_PAYLOAD"


def test_export_start_refuses_missing_directory(export_control, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A nonexistent output directory fails the preflight like the route."""
    client, _db, service, sid, state, _tmp = export_control
    _expect_rejected(service, sid, state, _export_cmd(
        service, sid, state, height=_available_height(client, state["project_id"]),
        output_path=str(tmp_path / "no-such-dir" / "out.mp4"),
    ), "INVALID_PAYLOAD")


def test_export_cancel_stops_the_job(export_control, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A cancel request stops the running encode; the file is not published."""
    client, _db, service, sid, state, _tmp = export_control
    output = tmp_path / "cancelled.mp4"
    started = _execute(service, sid, state, _export_cmd(
        service, sid, state, height=720, output_path=str(output), quality="best",
    ))
    assert started["status"] == "persisted", json.dumps(started, default=str)
    job_id = str(started["canonical"]["export_job_id"])
    cancelled = _execute(service, sid, state, _export_cmd(
        service, sid, state, kind="export_cancel", job_id=job_id
    ))
    assert cancelled["persisted"] is True
    job = _wait_job(service, sid, state, job_id)
    assert job["state"] == "cancelled", job


def test_export_status_unknown_job_is_typed_error(export_control) -> None:  # type: ignore[no-untyped-def]
    _client, _db, service, sid, state, _tmp = export_control
    _expect_rejected(service, sid, state, _export_cmd(
        service, sid, state, kind="export_status", job_id="no-such-job"
    ), "TARGET_NOT_FOUND")


def test_export_start_conflicts_with_running_export(export_control, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The single-active-export rule holds across both entry points."""
    _client, _db, service, sid, state, _tmp = export_control
    first = _execute(service, sid, state, _export_cmd(
        service, sid, state, height=720,
        output_path=str(tmp_path / "slow.mp4"), quality="best",
    ))
    assert first["status"] == "persisted", first
    job_id = str(first["canonical"]["export_job_id"])
    _expect_rejected(service, sid, state, _export_cmd(
        service, sid, state, height=720,
        output_path=str(tmp_path / "second.mp4"),
    ), "EXPORT_BUSY")
    _wait_job(service, sid, state, job_id)
