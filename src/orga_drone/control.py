"""Opt-in process-local Studio control. No media or credentials leave this boundary."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from datetime import datetime
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from orga_drone.timeline_actions import TimelineActionError, apply_timeline, timeline_view
from orga_drone.export.studio_encoder import StudioExportError
from orga_drone.studio_export import start_studio_export_job
from orga_drone.studio_history import transactional_story_undo, capture_story
from orga_drone.project_actions import (
    ProjectActionError, create_project, open_project, rename_project, delete_project,
    project_view, project_transaction, read_projects,
)
from orga_drone.db import Database
from orga_drone.lut_library import list_catalog
from orga_drone.library_actions import LibraryActionError, read_media
from orga_drone.media_files import resolve_media_file
from orga_drone.studio_estimate import effective_seconds
from orga_drone.studio_actions import (
    LIMITS,
    ActionValidationError,
    action_catalog,
    canonical as action_canonical,
    lut_catalog,
    merge_properties,
    parse_properties_patch,
    prepare_action,
    properties,
    resolve_action_spec,
    validate_action_params,
    validate_clip_effect_settings,
)
from orga_drone.studio_history import (
    history_flags,
    history_guard,
    history_revision,
    transactional_story_edit,
    undo_story,
)

LEASE_SECONDS = 3.0
MAX_COMMANDS = 1024
MAX_SAFE_INTEGER = 2**53 - 1
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class ControlError(Exception):
    def __init__(self, code: str, status: int = 409) -> None:
        self.code = code
        self.status = status


@dataclass(frozen=True)
class ExternalOperation:
    session_id: str
    project_id: int
    clip_id: int | None
    command_id: str
    revision: int
    fingerprint: str


def shape(
    value: Any, allowed: set[str], required: set[str] | None = None
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) - allowed
        or (required or set()) - set(value)
    ):
        raise ControlError("INVALID_PAYLOAD", 400)
    return value


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ControlError("INVALID_IDENTIFIER", 400)
    return value


def positive_id(value: Any) -> int:
    if type(value) is not int or not 0 < value <= MAX_SAFE_INTEGER:
        raise ControlError("INVALID_IDENTIFIER", 400)
    return value


class ControlService:
    def __init__(self, db: Database, data_dir: Path) -> None:
        self.db = db
        self.data_dir = data_dir
        self.instance = secrets.token_hex(24)
        self.digest: bytes | None = None
        self.session: dict[str, Any] | None = None
        self.commands: dict[str, dict[str, Any]] = {}
        self.latest_external: ExternalOperation | None = None
        self.reload_ticket: dict[str, Any] | None = None
        self.timeline_anchor: int | None = None
        self.timeline_anchor_revision = 0
        self.clock = time.monotonic
        # Injected by the app after the job store exists (issue #282):
        # export_status/export_cancel/export_start share the HTTP route's
        # store, so both paths see the same single active export.
        self.export_jobs: Any = None

    @property
    def enabled(self) -> bool:
        return self.digest is not None

    def authenticate(self, authorization: str) -> None:
        if not self.enabled:
            raise ControlError("CONTROL_DISABLED", 403)
        supplied = authorization.removeprefix("Bearer ")
        if not authorization.startswith("Bearer ") or not hmac.compare_digest(
            hashlib.sha256(supplied.encode()).digest(), self.digest or b""
        ):
            raise ControlError("INVALID_CREDENTIAL", 401)

    def enable(self, payload: Any) -> dict[str, Any]:
        body = shape(
            payload, {"session_id", "pairing_key"}, {"session_id", "pairing_key"}
        )
        sid = identifier(body["session_id"])
        key = body["pairing_key"]
        if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ControlError("INVALID_PAIRING_KEY", 400)
        with history_guard():
            if (
                self.enabled
                and self.session
                and self.clock() - self.session["seen"] <= LEASE_SECONDS
                and not self.session.get("fenced")
                and self.session["session_id"] != sid
            ):
                raise ControlError("EDITOR_SESSION_CONFLICT")
            self.disable()
            self.digest = hashlib.sha256(key.encode()).digest()
            self.session = {"session_id": sid, "seen": self.clock(), "state": None}
            return {"enabled": True}

    def disable(self) -> dict[str, Any]:
        with history_guard():
            self.reload_ticket = None
            self.digest = None
            self.session = None
            self.latest_external = None
            for cmd in self.commands.values():
                if (
                    not cmd["result"]["persisted"]
                    and cmd["result"]["status"] == "queued"
                ):
                    cmd["result"].update(
                        status="rejected", error_code="CONTROL_DISABLED"
                    )
            return {"enabled": False}

    def _session(self, sid: str | None = None, *, allow_fenced: bool = False) -> dict[str, Any]:
        if not self.enabled:
            raise ControlError("CONTROL_DISABLED", 403)
        session = self.session
        if session is None or self.clock() - session["seen"] > LEASE_SECONDS:
            raise ControlError("EDITOR_DISCONNECTED")
        if sid is not None and sid != session["session_id"]:
            raise ControlError("EDITOR_SESSION_CONFLICT")
        if session.get("fenced") and not allow_fenced:
            raise ControlError("STALE_STATE")
        return session

    def _state(self, payload: Any) -> dict[str, Any]:
        body = shape(
            payload,
            {
                "project_id",
                "clip_id",
                "selection_revision",
                "playhead_s",
                "playing",
                "busy",
                "ready",
            },
            {
                "project_id",
                "clip_id",
                "selection_revision",
                "playhead_s",
                "playing",
                "busy",
                "ready",
            },
        )
        positive_id(body["project_id"])
        if body["clip_id"] is not None:
            positive_id(body["clip_id"])
        if (
            type(body["selection_revision"]) is not int
            or not 0 <= body["selection_revision"] <= MAX_SAFE_INTEGER
        ):
            raise ControlError("INVALID_PAYLOAD", 400)
        if any(type(body[k]) is not bool for k in ("playing", "busy", "ready")):
            raise ControlError("INVALID_PAYLOAD", 400)
        if (
            type(body["playhead_s"]) not in (int, float)
            or not 0 <= body["playhead_s"] <= 1_000_000_000
        ):
            raise ControlError("INVALID_PAYLOAD", 400)
        return dict(body)

    def _fingerprint(
        self, project_id: int, connection: sqlite3.Connection | None = None
    ) -> str:
        def read(conn: sqlite3.Connection) -> str:
            rows = []
            for table in ("studio_projects", "studio_clips", "studio_audio_clips"):
                key = "id" if table == "studio_projects" else "project_id"
                rows.append(
                    [
                        tuple(r)
                        for r in conn.execute(
                            f"SELECT * FROM {table} WHERE {key} = ? ORDER BY id",
                            (project_id,),
                        ).fetchall()
                    ]
                )
            return hashlib.sha256(repr(rows).encode()).hexdigest()

        if connection is not None:
            return read(connection)
        with self.db.connect() as conn:
            return read(conn)

    def _token(self, state: dict[str, Any], connection: sqlite3.Connection | None = None) -> str:
        session = self._session()
        material = [
            self.instance,
            session["session_id"],
            state["project_id"],
            state["clip_id"],
            state["selection_revision"],
            history_revision(),
            self._fingerprint(state["project_id"], connection),
        ]
        return hashlib.sha256(repr(material).encode()).hexdigest()

    def poll(self, payload: Any) -> dict[str, Any]:
        body = shape(payload, {"session_id", "state"}, {"session_id", "state"})
        sid = identifier(body["session_id"])
        state = self._state(body["state"])
        with history_guard():
            if not self.enabled:
                return {"enabled": False}
            # A committed context change retires this editor. Recovery only:
            # ignore its old state and return terminal navigation outcomes even
            # after its editing lease expires; never renew or revive the lease.
            retired = self.session
            if retired is not None and retired["session_id"] == sid and retired.get("fenced"):
                return {"enabled": True, "commands": [
                    self.result(cid) for cid, cmd in self.commands.items()
                    if cmd["payload"]["session_id"] == sid
                    and cmd["result"].get("navigation_required")
                    and cmd["result"]["persisted"]
                ]}
            session = self._session(sid)
            previous = session["state"]
            if (
                previous
                and state["selection_revision"] < previous["selection_revision"]
            ):
                raise ControlError("STALE_SELECTION")
            session.update(seen=self.clock(), state=state)
            pending = [
                self.bridge_result(cid)
                for cid, cmd in self.commands.items()
                if cmd["payload"]["session_id"] == sid
                and (
                    cmd["result"]["status"] == "queued"
                    or (
                        cmd["result"]["persisted"]
                        and not cmd["result"]["ui_applied"]
                        and cmd.get("ui_revision") == history_revision()
                        and cmd["payload"]["project_id"] == state["project_id"]
                        and (cmd["payload"]["type"] == "project_action" or cmd["payload"]["clip_id"] == state["clip_id"])
                    )
                )
            ]
            return {
                "enabled": True,
                "state_token": self._token(state),
                "commands": pending,
            }

    def _clip(self, project_id: int, clip_id: int) -> Any:
        clip = next(
            (c for c in self.db.list_studio_items(project_id) if c.id == clip_id), None
        )
        if clip is None:
            raise ControlError("TARGET_NOT_FOUND", 404)
        # Photos support the same color actions as videos (image, look, hsl,
        # wheels, detail) through the shared routes and shared effect
        # settings storage; title cards and other item kinds stay
        # unsupported (issue #296).
        if clip.item_kind != "media" or clip.kind not in {"video", "photo"}:
            raise ControlError("UNSUPPORTED_CLIP")
        media = self.db.get_media(clip.media_id) if clip.media_id else None
        if media is None or resolve_media_file(self.db, media) is None:
            raise ControlError("MEDIA_UNAVAILABLE")
        try:
            validate_clip_effect_settings(clip.effect_settings)
        except ActionValidationError as exc:
            raise ControlError(exc.code) from None
        return clip

    def editor_state(self) -> dict[str, Any]:
        with history_guard():
            session = self._session()
            state = session["state"]
            if state is None:
                raise ControlError("EDITOR_NOT_READY")
            result = dict(
                state, session_id=session["session_id"], state_token=self._token(state)
            )
            try:
                clip = self._clip(state["project_id"], state["clip_id"])
                result["properties"] = properties(clip.effect_settings)
            except ControlError as exc:
                result.update(ready=False, error_code=exc.code, properties=None)
            return result

    def available_controls(self) -> dict[str, Any]:
        self._session()
        return {
            "controls": {
                **{
                    k: {"type": "integer", "minimum": v[0], "maximum": v[1]}
                    for k, v in LIMITS.items()
                },
                "creative_lut_id": {"type": "string_or_null"},
            },
            "creative_luts": [
                {"id": e.asset_name, "name": e.display_name}
                for e in list_catalog(self.db, self.data_dir)
                if e.file_present
            ],
            **action_catalog(),
        }

    def available_actions(self) -> dict[str, Any]:
        self._session()
        return action_catalog()

    def read_action(self, payload: Any) -> dict[str, Any]:
        fields = {"session_id", "action", "action_version", "target", "params"}
        body = shape(payload, fields, fields)
        if not isinstance(body["target"], dict):
            raise ControlError("INVALID_TARGET", 400)
        with history_guard():
            self._session(identifier(body["session_id"]))
            try:
                spec = resolve_action_spec(body["action"], body["action_version"])
                if spec.scope == "library":
                    result = read_media(self.db, spec.name, body["target"], body["params"])
                elif spec.scope == "project_read":
                    validate_action_params(spec, body["params"])
                    result = read_projects(self.db, spec.name, body["target"])
                else:
                    raise ControlError("INVALID_ACTION_SCOPE", 400)
            except (ActionValidationError, LibraryActionError, ProjectActionError) as exc:
                status = {"TARGET_NOT_FOUND": 404, "MEDIA_UNAVAILABLE": 409}.get(exc.code, 400)
                raise ControlError(exc.code, status) from None
            except (sqlite3.Error, ValueError, TypeError, OverflowError):
                raise ControlError("DATABASE_ERROR", 500) from None
            return {"action": spec.name, "action_version": spec.version,
                    "session_id": body["session_id"], "result": result}

    def _patch(self, payload: Any) -> dict[str, Any]:
        try:
            return parse_properties_patch(payload)
        except ActionValidationError as exc:
            raise ControlError(exc.code, 400) from None

    def _timeline_command(self, body: dict[str, Any]) -> dict[str, Any] | None:
        if body["type"] == "timeline_action":
            return body
        if body["type"] != "undo_last_change":
            return None
        original = self.commands.get(body.get("undo_command_id", ""))
        if original and original["payload"].get("type") == "timeline_action":
            return original["payload"]
        return None

    def _expire_reload_ticket(self) -> None:
        ticket = self.reload_ticket
        if ticket is not None and self.clock() > ticket["deadline"]:
            self.reload_ticket = None

    def _check(self, body: dict[str, Any], state: dict[str, Any]) -> None:
        self._session(body["session_id"])
        project_action = body["type"] == "project_action"
        export_command = body["type"] in (
            "export_start",
            "export_status",
            "export_cancel",
        )
        timeline_command = self._timeline_command(body)
        timeline_undo = (
            body["type"] == "undo_last_change" and timeline_command is not None
        )
        timeline = timeline_command is not None
        if timeline:
            self._expire_reload_ticket()
        action = timeline_command["action"] if timeline_command else ""
        selection_bound = action in {"timeline.remove", "timeline.trim"}
        expected_clip = self.timeline_anchor if timeline_undo else body["clip_id"]
        if timeline_undo and expected_clip != state["clip_id"]:
            raise ControlError("UNDO_CONFLICT")
        if body["project_id"] != state["project_id"]:
            raise ControlError("STALE_SELECTION")
        if timeline and not timeline_undo and not selection_bound:
            # Story-scoped add/reorder may omit clip identity; if supplied, it
            # must still match the editor's current selection.
            if body["clip_id"] is not None and body["clip_id"] != state["clip_id"]:
                raise ControlError("STALE_SELECTION")
        elif not project_action and not export_command and expected_clip != state["clip_id"]:
            raise ControlError("STALE_SELECTION")
        if timeline_undo and self.timeline_anchor is None and state["selection_revision"] != self.timeline_anchor_revision:
            raise ControlError("UNDO_CONFLICT")
        if body["type"] == "undo_last_change":
            operation = self.latest_external
            if operation != ExternalOperation(
                session_id=body["session_id"],
                project_id=body["project_id"],
                clip_id=body["clip_id"],
                command_id=body["undo_command_id"],
                revision=history_revision(),
                fingerprint=self._fingerprint(body["project_id"]),
            ):
                raise ControlError("UNDO_CONFLICT")
        if body["expected_state_token"] != self._token(state):
            raise ControlError("STALE_STATE")
        if (
            not export_command
            and (
                state["playing"]
                or state["busy"]
                or (not project_action and not timeline and not state["ready"])
            )
        ):
            # Export commands never mutate editor state; a playing or busy
            # editor does not block starting/observing a render job.
            raise ControlError("EDITOR_BUSY")
        if project_action or timeline:
            opened = self.db.get_open_studio_project()
            if opened is None or opened.id != body["project_id"]:
                raise ControlError("STALE_STATE")
            if timeline and self.reload_ticket is not None:
                raise ControlError("EDITOR_BUSY")
        elif not export_command:
            self._clip(body["project_id"], body["clip_id"])

    def submit(self, payload: Any) -> dict[str, Any]:
        body = shape(
            payload,
            {
                "command_id",
                "type",
                "session_id",
                "project_id",
                "clip_id",
                "expected_state_token",
                "expires_at",
                "properties",
                "undo_command_id",
                "action",
                "action_version",
                "params",
                "height",
                "quality",
                "output_path",
                "job_id",
            },
            {
                "command_id",
                "type",
                "session_id",
                "project_id",
                "clip_id",
                "expected_state_token",
                "expires_at",
            },
        )
        cid = identifier(body["command_id"])
        identifier(body["session_id"])
        positive_id(body["project_id"])
        if body["type"] in ("export_status", "export_cancel"):
            # Job commands are project-scoped reads/cancel only.
            if body["clip_id"] is not None:
                raise ControlError("INVALID_TARGET", 400)
            if not isinstance(body["job_id"], str) or not body["job_id"]:
                raise ControlError("INVALID_PAYLOAD", 400)
        elif body["type"] == "export_start":
            if body["clip_id"] is not None:
                raise ControlError("INVALID_TARGET", 400)
            if not isinstance(body.get("height"), int) or isinstance(body.get("height"), bool):
                raise ControlError("INVALID_PAYLOAD", 400)
            if not isinstance(body.get("output_path"), str) or not str(body["output_path"]).strip():
                raise ControlError("INVALID_PAYLOAD", 400)
            if body.get("quality") is not None and not isinstance(body["quality"], str):
                raise ControlError("INVALID_PAYLOAD", 400)
            # "overwrite" is not an accepted field at all: shape() rejects it,
            # so a silent overwrite is impossible through the Control API and
            # an existing file stays a 409-class error.
        elif body["type"] in {"timeline_action", "undo_last_change"} and body["clip_id"] is None:
            pass
        elif body["type"] == "project_action":
            if body["clip_id"] is not None:
                raise ControlError("INVALID_TARGET", 400)
        else:
            positive_id(body["clip_id"])
        if (
            not isinstance(body["expected_state_token"], str)
            or len(body["expected_state_token"]) != 64
        ):
            raise ControlError("INVALID_PAYLOAD", 400)
        if body["type"] not in (
            "set_clip_properties",
            "undo_last_change",
            "apply_action",
            "project_action",
            "timeline_action",
            "export_start",
            "export_status",
            "export_cancel",
        ):
            raise ControlError("UNKNOWN_COMMAND", 400)
        if body["type"] in ("export_status", "export_cancel"):
            if set(body) & {"properties", "undo_command_id", "action",
                            "action_version", "params", "height", "quality",
                            "output_path"}:
                raise ControlError("INVALID_PAYLOAD", 400)
        elif body["type"] == "export_start":
            if set(body) & {"properties", "undo_command_id", "action",
                            "action_version", "params", "job_id"}:
                raise ControlError("INVALID_PAYLOAD", 400)
        elif body["type"] == "set_clip_properties":
            if "undo_command_id" in body or set(body) & {
                "action",
                "action_version",
                "params",
            }:
                raise ControlError("INVALID_PAYLOAD", 400)
            self._patch(body.get("properties"))
        elif body["type"] in {"apply_action", "project_action", "timeline_action"}:
            if "properties" in body or "undo_command_id" in body:
                raise ControlError("INVALID_PAYLOAD", 400)
            if not {"action", "action_version", "params"} <= set(body):
                raise ControlError("INVALID_PAYLOAD", 400)
            try:
                spec = resolve_action_spec(
                    body["action"], body["action_version"]
                )
                expected_scope = {"project_action": "project", "timeline_action": "timeline"}.get(body["type"], "clip")
                if spec.scope != expected_scope:
                    raise ControlError("INVALID_ACTION_SCOPE", 400)
                validate_action_params(spec, body["params"])
                if spec.name in {"timeline.remove", "timeline.trim"}:
                    positive_id(body["clip_id"])
            except ActionValidationError as exc:
                raise ControlError(exc.code, 400) from None
        else:
            if "properties" in body or "undo_command_id" not in body:
                raise ControlError("INVALID_PAYLOAD", 400)
            if set(body) & {"action", "action_version", "params"}:
                raise ControlError("INVALID_PAYLOAD", 400)
            identifier(body["undo_command_id"])
        expiry = body["expires_at"]
        if type(expiry) not in (int, float) or not 0 < expiry <= 1_000_000_000_000:
            raise ControlError("INVALID_PAYLOAD", 400)
        with history_guard():
            if cid in self.commands:
                if (
                    self.session is None
                    or self.session["session_id"] != body["session_id"]
                ):
                    raise ControlError("EDITOR_SESSION_CONFLICT")
                if self.commands[cid]["payload"] != body:
                    raise ControlError("COMMAND_ID_CONFLICT")
                return self.result(cid)
            if len(self.commands) >= MAX_COMMANDS:
                raise ControlError("COMMAND_CAPACITY_REACHED", 429)
            if expiry <= time.time():
                raise ControlError("COMMAND_EXPIRED")
            if expiry > time.time() + 30:
                raise ControlError("INVALID_EXPIRY", 400)
            session = self._session(body["session_id"])
            if session["state"] is None:
                raise ControlError("EDITOR_NOT_READY")
            self._check(body, session["state"])
            timeline_scope = self._timeline_command(body) is not None
            scope = (
                "timeline"
                if timeline_scope
                else "project" if body["type"] == "project_action" else None
            )
            self.commands[cid] = {
                "payload": dict(body),
                "deadline": self.clock() + expiry - time.time(),
                "result": {
                    "command_id": cid,
                    "status": "queued",
                    "persisted": False,
                    "ui_applied": False,
                    "preview_status": "not_requested",
                    **({"scope": scope} if scope else {}),
                    **(
                        {
                            "action": body["action"],
                            "action_version": body["action_version"],
                        }
                        if body["type"] in {"apply_action", "project_action", "timeline_action"}
                        else {}
                    ),
                },
            }
            return self.result(cid)

    def result(self, cid: str) -> dict[str, Any]:
        cmd = self.commands.get(cid)
        if cmd is None:
            raise ControlError("COMMAND_NOT_FOUND", 404)
        result = cmd["result"]
        if result["status"] == "queued" and self.clock() > cmd["deadline"]:
            result.update(status="rejected", error_code="COMMAND_EXPIRED")
        if result["persisted"] and not result["ui_applied"]:
            result["status"] = "persisted_ui_unconfirmed"
        return dict(result)

    def external_result(self, cid: str) -> dict[str, Any]:
        with history_guard():
            session = self.session
            cmd = self.commands.get(cid)
            if cmd and (
                session is None or cmd["payload"]["session_id"] != session["session_id"]
            ):
                raise ControlError("EDITOR_SESSION_CONFLICT")
            return self.result(cid)

    def recover(self, payload: Any) -> dict[str, Any]:
        """Read an uncertain bridge outcome without renewing an editing lease."""
        body = shape(payload, {"session_id", "command_id"}, {"session_id", "command_id"})
        sid, cid = identifier(body["session_id"]), identifier(body["command_id"])
        with history_guard():
            if not self.enabled:
                raise ControlError("CONTROL_DISABLED", 403)
            if self.session is None or self.session["session_id"] != sid:
                raise ControlError("EDITOR_SESSION_CONFLICT")
            cmd = self.commands.get(cid)
            if cmd is None or cmd["payload"]["session_id"] != sid:
                raise ControlError("COMMAND_NOT_FOUND", 404)
            return self.bridge_result(cid)

    def execute(self, payload: Any) -> dict[str, Any]:
        body = shape(
            payload,
            {"command_id", "session_id", "state"},
            {"command_id", "session_id", "state"},
        )
        state = self._state(body["state"])
        with history_guard():
            self._session(identifier(body["session_id"]), allow_fenced=True)
            cmd = self.commands.get(identifier(body["command_id"]))
            if cmd is None or cmd["payload"]["session_id"] != body["session_id"]:
                raise ControlError("COMMAND_NOT_FOUND", 404)
            result = self.result(body["command_id"])
            if result["status"] != "queued":
                return self.bridge_result(body["command_id"])
            target = cmd["payload"]
            try:
                self._check(target, state)
                if target["type"] in (
                    "export_start",
                    "export_status",
                    "export_cancel",
                ):
                    return self._execute_export(cmd)
                if target["type"] == "project_action":
                    if str(target.get("action", "")).startswith("music."):
                        return self._execute_music(cmd, state)
                    return self._execute_project(cmd, state)
                if target["type"] == "timeline_action" or (
                    target["type"] == "undo_last_change"
                    and self._timeline_command(target) is not None
                ):
                    return self._execute_timeline(cmd, state)
                expected_fingerprint = self._fingerprint(target["project_id"])
                clip = self._clip(target["project_id"], target["clip_id"])
                available_luts = lut_catalog(self.db, self.data_dir)
                if target["type"] == "undo_last_change":
                    # Capture canonical values from the existing undo snapshot before commit.
                    from orga_drone.studio_history import guarded_undo_values

                    raw = guarded_undo_values(self.db, target["project_id"], clip.id)
                    self._merge(
                        raw,
                        {"contrast": properties(raw)["contrast"]},
                        available_luts,
                    )
                    canonical = action_canonical(raw)
                    self._session(body["session_id"])
                    if self.clock() > cmd["deadline"]:
                        raise ControlError("COMMAND_EXPIRED")
                    if not undo_story(self.db, target["project_id"]):
                        raise ControlError("UNDO_CONFLICT")
                    self.latest_external = None
                    no_op = False
                else:
                    if target["type"] == "apply_action":
                        spec = resolve_action_spec(
                            target["action"], target["action_version"]
                        )
                        raw = prepare_action(
                            spec,
                            clip.effect_settings,
                            target["params"],
                            available_luts,
                            self.data_dir,
                            clip_duration_s=(
                                effective_seconds(
                                    kind=clip.kind,
                                    photo_duration_s=clip.photo_duration_s,
                                    duration_s=clip.duration_s,
                                    available=bool(clip.available),
                                    source_in_s=clip.source_start,
                                    source_out_s=clip.source_end,
                                    playback_speed=clip.playback_speed,
                                )
                                if clip.kind in {"photo", "video"}
                                else None
                            ),
                        )
                        no_op = action_canonical(raw) == action_canonical(
                            clip.effect_settings
                        )
                    else:
                        raw = self._merge(
                            clip.effect_settings,
                            target["properties"],
                            available_luts,
                        )
                        no_op = properties(raw) == properties(
                            clip.effect_settings
                        )
                    canonical = action_canonical(raw)
                    self._session(body["session_id"])
                    if self.clock() > cmd["deadline"]:
                        raise ControlError("COMMAND_EXPIRED")
                    if not no_op:
                        with transactional_story_edit(
                            self.db, target["project_id"]
                        ) as conn:
                            if (
                                self._fingerprint(target["project_id"], conn)
                                != expected_fingerprint
                            ):
                                raise ControlError("STALE_STATE")
                            conn.execute(
                                "UPDATE studio_clips SET effect_settings = ? WHERE id = ? AND project_id = ?",
                                (raw, clip.id, target["project_id"]),
                            )
                            conn.execute(
                                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                                (
                                    datetime.now().isoformat(timespec="seconds"),
                                    target["project_id"],
                                ),
                            )
                            fingerprint = self._fingerprint(target["project_id"], conn)
                        self.latest_external = ExternalOperation(
                            session_id=body["session_id"],
                            project_id=target["project_id"],
                            clip_id=clip.id,
                            command_id=target["command_id"],
                            revision=history_revision(),
                            fingerprint=fingerprint,
                        )
                cmd["result"].update(
                    status="persisted",
                    persisted=True,
                    no_op=no_op,
                    clip_id=clip.id,
                    project_id=target["project_id"],
                    canonical=canonical,
                    **history_flags(target["project_id"]),
                )
                if target["type"] == "undo_last_change":
                    cmd["result"]["undone_command_id"] = target["undo_command_id"]
                elif target["type"] == "apply_action":
                    cmd["result"]["action"] = target["action"]
                    cmd["result"]["action_version"] = target["action_version"]
                cmd["ui_revision"] = history_revision()
            except ControlError as exc:
                cmd["result"].update(status="rejected", error_code=exc.code)
            except (ActionValidationError, ProjectActionError, TimelineActionError) as exc:
                cmd["result"].update(status="rejected", error_code=exc.code)
            except Exception:
                cmd["result"].update(status="rejected", error_code="DATABASE_ERROR")
            return dict(cmd["result"])

    def _execute_timeline(self, cmd: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        target = cmd["payload"]
        pid = target["project_id"]
        undo = target["type"] == "undo_last_change"

        def validate(conn: sqlite3.Connection) -> None:
            if self._token(state, conn) != target["expected_state_token"]:
                raise ControlError("STALE_STATE")

        context = (
            transactional_story_undo(self.db, pid, validate=validate)
            if undo
            else transactional_story_edit(self.db, pid)
        )
        # Generate fallible/random material before committing.
        ticket = secrets.token_hex(32)
        with context as conn:
            if conn is None:
                raise ControlError("UNDO_CONFLICT")
            if not undo and self._token(state, conn) != target["expected_state_token"]:
                raise ControlError("STALE_STATE")
            before = capture_story(self.db, pid, connection=conn)
            affected = target["clip_id"]
            try:
                if not undo:
                    affected = apply_timeline(
                        self.db,
                        pid,
                        affected,
                        target["action"],
                        target["params"],
                        connection=conn,
                    )
            except TimelineActionError:
                raise
            except (ValueError, OverflowError):
                raise TimelineActionError("INVALID_PARAMS") from None
            canonical = timeline_view(self.db, pid, conn)
            fingerprint = self._fingerprint(pid, conn)
            no_op = not undo and before == capture_story(
                self.db, pid, connection=conn
            )
            if no_op:
                anchor = (
                    state["clip_id"]
                    if state["clip_id"] in canonical["ordered_ids"]
                    else None
                )
            else:
                anchor = (
                    target["clip_id"]
                    if target["clip_id"] in canonical["ordered_ids"]
                    else None
                )
            self._session(target["session_id"])
            if self.clock() > cmd["deadline"]:
                raise ControlError("COMMAND_EXPIRED")
        if undo:
            self.latest_external = None
        elif not no_op:
            self.latest_external = ExternalOperation(
                session_id=target["session_id"],
                project_id=pid,
                clip_id=target["clip_id"],
                command_id=target["command_id"],
                revision=history_revision(),
                fingerprint=fingerprint,
            )
        elif self.latest_external is not None and self.latest_external.project_id == pid:
            # A no-op timeline helper may still bump project updated_at. Keep
            # the previous guarded-Undo association valid.
            self.latest_external = replace(
                self.latest_external,
                revision=history_revision(),
                fingerprint=fingerprint,
            )
        if not no_op:
            self.timeline_anchor = anchor
            self.timeline_anchor_revision = state["selection_revision"]
        reload_required = not no_op
        cmd["timeline_fingerprint"] = fingerprint
        cmd["result"].update(
            status="persisted",
            persisted=True,
            scope="timeline",
            project_id=pid,
            clip_id=target["clip_id"],
            affected_clip_id=affected,
            canonical=canonical,
            no_op=no_op,
            reload_required=reload_required,
            selection_clip_id=anchor,
            **history_flags(pid),
        )
        if undo:
            cmd["result"]["undone_command_id"] = target["undo_command_id"]
        cmd["ui_revision"] = history_revision()
        if reload_required:
            self.reload_ticket = {
                "ticket": ticket,
                "command_id": target["command_id"],
                "session_id": target["session_id"],
                "project_id": pid,
                "fingerprint": fingerprint,
                "anchor": anchor,
                "revision": state["selection_revision"],
                "deadline": self.clock() + 30,
            }
        return self.bridge_result(target["command_id"])

    def bridge_result(self, cid: str) -> dict[str, Any]:
        self._expire_reload_ticket()
        result = self.result(cid)
        ticket = self.reload_ticket
        if ticket and ticket["command_id"] == cid:
            result["resume_ticket"] = ticket["ticket"]
        return result

    def resume(self, payload: Any) -> dict[str, Any]:
        body = shape(payload, {"ticket", "project_id"}, {"ticket", "project_id"})
        with history_guard():
            self._expire_reload_ticket()
            ticket = self.reload_ticket
            if (
                not self.enabled
                or ticket is None
                or not isinstance(body["ticket"], str)
                or not hmac.compare_digest(body["ticket"], ticket["ticket"])
            ):
                raise ControlError("INVALID_RESUME_TICKET")
            if (
                body["project_id"] != ticket["project_id"]
                or self._fingerprint(ticket["project_id"])
                != ticket["fingerprint"]
            ):
                self.reload_ticket = None
                raise ControlError("STALE_STATE")
            opened = self.db.get_open_studio_project()
            if opened is None or opened.id != ticket["project_id"]:
                raise ControlError("STALE_STATE")
            assert self.session is not None
            self.reload_ticket = None
            self.session.update(seen=self.clock(), state=None)
            return {
                "session_id": ticket["session_id"],
                "selection_revision": ticket["revision"],
                "selection_clip_id": ticket["anchor"],
                "command_id": ticket["command_id"],
            }

    def _execute_export(self, cmd: dict[str, Any]) -> dict[str, Any]:
        """export_start/status/cancel share the HTTP route's job store so both
        paths launch the same render pipeline (issue #282)."""
        from orga_drone.studio_export import (
            prepare_studio_export,
            run_studio_export,
        )

        target = cmd["payload"]
        store = self.export_jobs
        if store is None:
            raise ControlError("EDITOR_NOT_READY")
        kind = target["type"]
        if kind == "export_status":
            job = store.get(str(target["job_id"]))
            if job is None:
                raise ControlError("TARGET_NOT_FOUND", 404)
            cmd["result"].update(
                status="persisted",
                persisted=True,
                ui_applied=False,
                canonical={"export_job": job.to_dict()},
                no_op=False,
            )
            return cmd["result"]
        if kind == "export_cancel":
            event = store.cancel_event(str(target["job_id"]))
            if event is None:
                raise ControlError("TARGET_NOT_FOUND", 404)
            event.set()
            cmd["result"].update(
                status="persisted",
                persisted=True,
                ui_applied=False,
                canonical={"cancel_requested": str(target["job_id"])},
                no_op=False,
            )
            return cmd["result"]
        # export_start: same preflight + same pipeline as the HTTP route.
        output_path = str(target["output_path"])
        try:
            prepare_studio_export(
                self.db,
                height=int(target["height"]),
                output_path=Path(output_path),
                project_id=target["project_id"],
                quality=target.get("quality"),
            )
        except StudioExportError as exc:
            raise ControlError("INVALID_PAYLOAD", 409) from exc
        def work(on_progress, cancel_event):  # type: ignore[no-untyped-def]
            return run_studio_export(
                self.db,
                height=int(target["height"]),
                output_path=Path(output_path),
                project_id=target["project_id"],
                quality=target.get("quality"),
                on_progress=on_progress,
                cancel_event=cancel_event,
            )

        try:
            job_id = start_studio_export_job(
                store, work, lambda message: message
            )
        except StudioExportError as exc:
            raise ControlError("EXPORT_BUSY", 409) from exc
        cmd["result"].update(
            status="persisted",
            persisted=True,
            ui_applied=False,
            canonical={"export_job_id": job_id, "started_at": time.time()},
            no_op=False,
        )
        return cmd["result"]

    def _execute_music(self, cmd: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        """Project-scoped music commands (issue #281 part 2). The music DB
        methods open their own connections, so these run OUTSIDE the project
        transaction. Semantics mirror the UI routes exactly: append/update/
        remove/reorder are not story-history captures, set_start is."""
        from orga_drone.studio_history import story_edit

        target = cmd["payload"]
        pid, action, params = target["project_id"], target["action"], target["params"]
        opened = self.db.get_open_studio_project()
        if opened is None or opened.id != pid:
            raise ControlError("STALE_STATE")
        if self._token(state) != target["expected_state_token"]:
            raise ControlError("STALE_STATE")
        self._session(target["session_id"])
        if self.clock() > cmd["deadline"]:
            raise ControlError("COMMAND_EXPIRED")
        try:
            if action == "music.append":
                # Same file validation as the UI route (existence + type).
                from orga_drone.export.music_mix import validate_music_file_path

                path = validate_music_file_path(str(params["file_path"]))
                self.db.append_studio_music(pid, str(path))
            elif action == "music.update":
                self.db.patch_studio_music_clip(
                    pid,
                    int(params["clip_id"]),
                    volume=float(params["volume"]),
                    fade_in_s=float(params["fade_in_s"]),
                    fade_out_s=float(params["fade_out_s"]),
                    loop=bool(params["loop"]),
                )
            elif action == "music.remove":
                if not self.db.delete_studio_music_clip(pid, int(params["clip_id"])):
                    raise ControlError("TARGET_NOT_FOUND", 404)
            elif action == "music.reorder":
                self.db.reorder_studio_music(pid, [int(item) for item in params["ordered_ids"]])
            elif action == "music.set_start":
                with story_edit(self.db, pid):
                    self.db.set_studio_music_start_s(pid, float(params["start_s"]))
            else:
                raise ControlError("UNKNOWN_ACTION", 400)
        except FileNotFoundError as exc:
            raise ControlError("INVALID_PAYLOAD", 400) from exc
        except ValueError as exc:
            # Music state errors (loop_single_only, not found, offline file)
            # are payload problems, not database faults.
            raise ControlError("INVALID_PAYLOAD", 400) from exc
        self.latest_external = None
        cmd["result"].update(
            status="persisted",
            persisted=True,
            ui_applied=False,
            scope="project",
            project_id=pid,
            clip_id=None,
            canonical={"music_action": action},
            no_op=False,
            navigation_required=True,
            **history_flags(pid),
        )
        cmd["ui_revision"] = history_revision()
        # The editor's soundtrack view is stale; reload like project.open.
        self.reload_ticket = None
        assert self.session is not None
        self.session["fenced"] = True
        return cmd["result"]

    def _execute_project(self, cmd: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        target = cmd["payload"]
        pid, action, params = target["project_id"], target["action"], target["params"]
        with project_transaction(self.db) as conn:
            opened = conn.execute("SELECT value FROM app_state WHERE key = ?",
                                  ("studio_last_opened_project_id",)).fetchone()
            if opened is None or str(opened[0]) != str(pid) or self._token(state, conn) != target["expected_state_token"]:
                raise ControlError("STALE_STATE")
            before = self.db.get_studio_project(pid, connection=conn)
            if before is None:
                raise ControlError("TARGET_NOT_FOUND", 404)
            if action == "project.create":
                project = create_project(self.db, params["title"], open_created=True, connection=conn)
            elif action == "project.open":
                project = open_project(self.db, params["project_id"], connection=conn)
            elif action == "project.rename":
                project = rename_project(self.db, pid, params["title"], connection=conn)
            elif action == "project.delete":
                if not delete_project(self.db, pid, connection=conn):
                    raise ControlError("TARGET_NOT_FOUND", 404)
                project = None
            else:
                raise ControlError("UNKNOWN_ACTION", 400)
            self._session(target["session_id"])
            if self.clock() > cmd["deadline"]:
                raise ControlError("COMMAND_EXPIRED")
            flags = history_flags(pid) if action == "project.rename" else {"can_undo": False, "can_redo": False}
            canonical = {"project": project_view(project) if project else None}
            no_op = action == "project.rename" and project is not None and project.title == before.title
        # Everything below uses committed values; no fallible DB read follows commit.
        self.latest_external = None
        navigation = action != "project.rename"
        cmd["result"].update(status="persisted", persisted=True, ui_applied=False,
                             scope="project", project_id=pid, clip_id=None,
                             canonical=canonical, no_op=no_op,
                             navigation_required=navigation, **flags)
        cmd["ui_revision"] = history_revision()
        if navigation:
            self.reload_ticket = None
            assert self.session is not None
            self.session["fenced"] = True
            for other in self.commands.values():
                if other is not cmd and other["result"]["status"] == "queued":
                    other["result"].update(status="rejected", error_code="STALE_STATE")
        return dict(cmd["result"])

    def _merge(
        self,
        raw: str,
        patch: dict[str, Any],
        available_luts: set[str] | None = None,
    ) -> str:
        catalog = (
            available_luts
            if available_luts is not None
            else lut_catalog(self.db, self.data_dir)
        )
        try:
            return merge_properties(raw, patch, catalog, self.data_dir)
        except ActionValidationError as exc:
            raise ControlError(exc.code, 400) from None

    def acknowledge(self, payload: Any) -> dict[str, Any]:
        body = shape(
            payload,
            {"command_id", "session_id", "preview_status"},
            {"command_id", "session_id", "preview_status"},
        )
        with history_guard():
            self._session(identifier(body["session_id"]), allow_fenced=True)
            cmd = self.commands.get(identifier(body["command_id"]))
            if cmd is None or cmd["payload"]["session_id"] != body["session_id"]:
                raise ControlError("COMMAND_NOT_FOUND", 404)
            if body["preview_status"] not in ("refresh_requested", "unavailable"):
                raise ControlError("INVALID_PAYLOAD", 400)
            if cmd["result"].get("navigation_required"):
                # Requesting a page switch is not proof the next editor loaded.
                return self.result(body["command_id"])
            if cmd["result"].get("scope") == "timeline":
                state = self.session["state"] if self.session else None
                fingerprint = cmd.get("timeline_fingerprint")
                if (
                    self.reload_ticket is not None
                    or state is None
                    or state["project_id"] != cmd["payload"]["project_id"]
                    or state["clip_id"] != cmd["result"]["selection_clip_id"]
                    or (
                        fingerprint is not None
                        and self._fingerprint(cmd["payload"]["project_id"])
                        != fingerprint
                    )
                ):
                    raise ControlError("STALE_STATE")
            if cmd["result"]["persisted"]:
                cmd["result"].update(
                    status="ui_applied",
                    ui_applied=True,
                    preview_status=body["preview_status"],
                )
            return self.result(body["command_id"])
