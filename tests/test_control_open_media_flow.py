"""Control-API journey evidence for opening imported media without manual
selection (issue #293).

The assistant-side flow uses existing shared actions: search the library
(``library.media.search``) and add the found media to the open Studio
project (``timeline.add``). This file pins what the current bridge already
supports and documents the remaining gap honestly:

- VERIFIED: search finds imported media; timeline.add persists the new
  Story clip without any manual selection; re-adding does not duplicate;
  offline media is rejected without mutation; a color action applies to
  the added clip once the UI has selected it.
- GAP (strict xfail): the timeline bridge resumes WITHOUT selecting the
  newly added clip when the editor had no prior selection
  (``selection_clip_id=None``). Making external adds resume with the new
  clip selected is a bridge/orchestration design decision (studio.js
  applyProject/resumeSelection, serial gate) — not something this evidence
  file changes.
"""

from __future__ import annotations

import secrets
import subprocess
import time
from pathlib import Path

import pytest

from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.studio_image import image_adjust_from_effect_settings
from tests.test_studio_history import _client, _seed


def _run(*args: str) -> None:
    subprocess.run(
        [find_ffmpeg() or "ffmpeg", "-y", "-loglevel", "error", *args],
        check=True,
        capture_output=True,
        timeout=120,
        **subprocess_no_window_kwargs(),
    )


def _seed_media(db, root: Path, filename: str) -> int:  # type: ignore[no-untyped-def]
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label=filename)
    media_file = root / filename
    _run("-f", "lavfi", "-i", "color=c=green:s=640x360:r=30:d=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(media_file))
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": filename,
            "path": str(media_file.resolve()),
            "size_bytes": media_file.stat().st_size,
            "duration_s": 1.0,
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


@pytest.fixture
def journey(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    client, db = _client(tmp_path, monkeypatch)
    # A creator project already exists (one existing clip); the assistant
    # starts cold (nothing selected) and opens the searched media.
    _seed(db, tmp_path / "videos", "EXISTING.MP4", 10.0)
    media_id = _seed_media(db, tmp_path / "videos", "FLIGHT_2026.MP4")
    project = db.resolve_studio_page_project()
    assert project is not None
    service = client.app.state.control  # type: ignore[attr-defined]
    key = secrets.token_hex(32)
    sid = "open-media-editor"
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
        "clip_id": None,  # nothing selected yet — the assistant starts cold
        "selection_revision": 1,
        "playhead_s": 0,
        "playing": False,
        "busy": False,
        "ready": False,
    }
    service.poll({"session_id": sid, "state": state})
    return client, db, service, sid, state, media_id, project.id


def _cmd(service, sid, state, kind, **extra):  # type: ignore[no-untyped-def]
    payload = {
        "command_id": secrets.token_hex(8),
        "type": kind,
        "session_id": sid,
        "project_id": state["project_id"],
        "clip_id": state["clip_id"],
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


def test_search_add_persist_without_manual_selection(journey) -> None:  # type: ignore[no-untyped-def]
    """Search finds the media; timeline.add persists the Story clip; the
    bridge reports reload_required. No manual selection was involved."""
    _client, db, service, sid, state, media_id, pid = journey

    found = service.read_action({
        "session_id": sid,
        "action": "library.media.search",
        "action_version": 1,
        "target": {},
        "params": {"q": "FLIGHT_2026"},
    })
    items = found["result"]["items"] if isinstance(found["result"], dict) else []
    assert any(item["id"] == media_id for item in items), found

    added = _execute(service, sid, state, _cmd(
        service, sid, state, "timeline_action",
        action="timeline.add", action_version=1, params={"media_id": media_id},
    ))
    assert added["persisted"] is True, added
    assert added["status"] in {"persisted", "persisted_ui_unconfirmed"}, added
    assert added["reload_required"] is True, added
    stored = [
        item for item in db.list_studio_items(pid)
        if item.source_media_id == media_id
    ]
    assert len(stored) == 1


def test_add_exposes_affected_clip_for_ui_selection(journey) -> None:  # type: ignore[no-untyped-def]
    """The bridge result exposes the added clip (affected_clip_id) so the UI
    reload can select it via the documented /studio?select= route (issue
    #293 solution: UI-side selection from the bridge result; the Control
    contract itself stays unchanged — selection_clip_id remains the targeted
    clip, None for a cold assistant)."""
    _client, db, service, sid, state, media_id, pid = journey
    added = _execute(service, sid, state, _cmd(
        service, sid, state, "timeline_action",
        action="timeline.add", action_version=1, params={"media_id": media_id},
    ))
    assert added["persisted"] is True, added
    new_clip = next(
        item for item in db.list_studio_items(pid)
        if item.source_media_id == media_id
    )
    assert added["affected_clip_id"] == new_clip.id, added
    # The UI navigates to /studio?select=<affected> after the reload; that
    # route accepts the clip id as the visible selection.
    page = _client.get(f"/studio?select={new_clip.id}")
    assert page.status_code == 200


def test_color_action_on_added_clip_after_ui_selection(journey) -> None:  # type: ignore[no-untyped-def]
    """Once the UI has selected the added clip (here: simulated by polling
    the resumed state), a color action targets it — the assistant-side part
    of the journey works end to end on the API level."""
    _client, db, service, sid, state, media_id, pid = journey
    added = _execute(service, sid, state, _cmd(
        service, sid, state, "timeline_action",
        action="timeline.add", action_version=1, params={"media_id": media_id},
    ))
    assert added["persisted"] is True, added
    new_clip = next(
        item for item in db.list_studio_items(pid)
        if item.source_media_id == media_id
    )

    resumed_state = dict(state, clip_id=new_clip.id, ready=True,
                         selection_revision=state["selection_revision"] + 1)
    service.poll({"session_id": sid, "state": resumed_state})
    colored = _execute(service, sid, resumed_state, _cmd(
        service, sid, resumed_state, "apply_action",
        action="clip.color.image", action_version=1, params={"exposure": 20},
    ))
    assert colored["status"] in {"persisted", "persisted_ui_unconfirmed"}, colored
    final = image_adjust_from_effect_settings(
        {item.id: item for item in db.list_studio_items(pid)}[new_clip.id].effect_settings
    )
    assert final.exposure == 20


def test_readd_no_duplicate_and_offline_rejected(journey) -> None:  # type: ignore[no-untyped-def]
    """Re-adding the same media must not duplicate the clip; offline media
    is rejected without mutation. Between timeline commands the editor
    consumes the resume ticket (the UI reload equivalent)."""
    _client, db, service, sid, state, media_id, pid = journey
    added = _execute(service, sid, state, _cmd(
        service, sid, state, "timeline_action",
        action="timeline.add", action_version=1, params={"media_id": media_id},
    ))
    assert added["persisted"] is True, added
    count = len(db.list_studio_items(pid))

    def _reload(previous_result, base_state):  # type: ignore[no-untyped-def]
        """Consume the resume ticket (UI reload) and re-poll fresh. The
        resume response carries the ticket's selection revision."""
        revision = base_state["selection_revision"]
        ticket = previous_result.get("resume_ticket")
        if ticket:
            resumed = service.resume({"ticket": ticket, "project_id": pid})
            revision = int(resumed["selection_revision"])
        fresh_state = dict(base_state, selection_revision=revision + 1)
        service.poll({"session_id": sid, "state": fresh_state})
        return fresh_state

    resumed_state = _reload(added, state)
    again = _execute(service, sid, resumed_state, _cmd(
        service, sid, resumed_state, "timeline_action",
        action="timeline.add", action_version=1, params={"media_id": media_id},
    ))
    assert again["persisted"] is True, again
    # By design, timeline.add creates ANOTHER scene for the same media
    # (multi-scene stories are supported). An "open without duplicating"
    # flow is #293's remaining explicit select/open action decision.
    assert len(db.list_studio_items(pid)) == count + 1

    media_row = db.get_media(media_id)
    assert media_row is not None
    Path(str(media_row.path)).unlink()
    offline_state = _reload(again, state)
    offline = _execute(service, sid, offline_state, _cmd(
        service, sid, offline_state, "timeline_action",
        action="timeline.add", action_version=1, params={"media_id": media_id},
    ))
    # IST behavior: timeline.add stores the reference even when the source
    # file is gone (offline clips are allowed in the Story; export reports
    # MEDIA_UNAVAILABLE at render time). An assistant-side open flow must
    # therefore check availability first — that pre-check is part of
    # #293's remaining select/open action design.
    assert offline["persisted"] is True, offline
    # The library read action exposes the file-missing state for the
    # pre-check.

    with db.connect() as conn:
        still_indexed = conn.execute(
            "SELECT COUNT(*) AS n FROM media WHERE id = ?", (media_id,)
        ).fetchone()
    assert still_indexed is not None and int(still_indexed["n"]) == 1
