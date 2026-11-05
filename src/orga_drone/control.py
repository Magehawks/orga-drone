"""Opt-in process-local Studio control. No media or credentials leave this boundary."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orga_drone.db import Database
from orga_drone.lut_library import list_catalog
from orga_drone.media_files import resolve_media_file
from orga_drone.studio_actions import (
    LIMITS,
    ActionValidationError,
    action_catalog,
    canonical as action_canonical,
    effect_settings_equal,
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
    clip_id: int
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
        self.clock = time.monotonic

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
                and self.session["session_id"] != sid
            ):
                raise ControlError("EDITOR_SESSION_CONFLICT")
            self.disable()
            self.digest = hashlib.sha256(key.encode()).digest()
            self.session = {"session_id": sid, "seen": self.clock(), "state": None}
            return {"enabled": True}

    def disable(self) -> dict[str, Any]:
        with history_guard():
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

    def _session(self, sid: str | None = None) -> dict[str, Any]:
        if not self.enabled:
            raise ControlError("CONTROL_DISABLED", 403)
        session = self.session
        if session is None or self.clock() - session["seen"] > LEASE_SECONDS:
            raise ControlError("EDITOR_DISCONNECTED")
        if sid is not None and sid != session["session_id"]:
            raise ControlError("EDITOR_SESSION_CONFLICT")
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

    def _token(self, state: dict[str, Any]) -> str:
        session = self._session()
        material = [
            self.instance,
            session["session_id"],
            state["project_id"],
            state["clip_id"],
            state["selection_revision"],
            history_revision(),
            self._fingerprint(state["project_id"]),
        ]
        return hashlib.sha256(repr(material).encode()).hexdigest()

    def poll(self, payload: Any) -> dict[str, Any]:
        body = shape(payload, {"session_id", "state"}, {"session_id", "state"})
        sid = identifier(body["session_id"])
        state = self._state(body["state"])
        with history_guard():
            if not self.enabled:
                return {"enabled": False}
            session = self._session(sid)
            previous = session["state"]
            if (
                previous
                and state["selection_revision"] < previous["selection_revision"]
            ):
                raise ControlError("STALE_SELECTION")
            session.update(seen=self.clock(), state=state)
            pending = [
                self.result(cid)
                for cid, cmd in self.commands.items()
                if cmd["payload"]["session_id"] == sid
                and (
                    cmd["result"]["status"] == "queued"
                    or (
                        cmd["result"]["persisted"]
                        and not cmd["result"]["ui_applied"]
                        and cmd.get("ui_revision") == history_revision()
                        and cmd["payload"]["project_id"] == state["project_id"]
                        and cmd["payload"]["clip_id"] == state["clip_id"]
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
        if clip.item_kind != "media" or clip.kind != "video":
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

    def _patch(self, payload: Any) -> dict[str, Any]:
        try:
            return parse_properties_patch(payload)
        except ActionValidationError as exc:
            raise ControlError(exc.code, 400) from None

    def _check(self, body: dict[str, Any], state: dict[str, Any]) -> None:
        self._session(body["session_id"])
        if (
            body["project_id"] != state["project_id"]
            or body["clip_id"] != state["clip_id"]
        ):
            raise ControlError("STALE_SELECTION")
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
        if state["playing"] or state["busy"] or not state["ready"]:
            raise ControlError("EDITOR_BUSY")
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
        ):
            raise ControlError("UNKNOWN_COMMAND", 400)
        if body["type"] == "set_clip_properties":
            if "undo_command_id" in body or set(body) & {
                "action",
                "action_version",
                "params",
            }:
                raise ControlError("INVALID_PAYLOAD", 400)
            self._patch(body.get("properties"))
        elif body["type"] == "apply_action":
            if "properties" in body or "undo_command_id" in body:
                raise ControlError("INVALID_PAYLOAD", 400)
            if not {"action", "action_version", "params"} <= set(body):
                raise ControlError("INVALID_PAYLOAD", 400)
            try:
                spec = resolve_action_spec(
                    body["action"], body["action_version"]
                )
                validate_action_params(spec, body["params"])
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
            self.commands[cid] = {
                "payload": dict(body),
                "deadline": self.clock() + expiry - time.time(),
                "result": {
                    "command_id": cid,
                    "status": "queued",
                    "persisted": False,
                    "ui_applied": False,
                    "preview_status": "not_requested",
                    **(
                        {
                            "action": body["action"],
                            "action_version": body["action_version"],
                        }
                        if body["type"] == "apply_action"
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

    def execute(self, payload: Any) -> dict[str, Any]:
        body = shape(
            payload,
            {"command_id", "session_id", "state"},
            {"command_id", "session_id", "state"},
        )
        state = self._state(body["state"])
        with history_guard():
            self._session(identifier(body["session_id"]))
            cmd = self.commands.get(identifier(body["command_id"]))
            if cmd is None or cmd["payload"]["session_id"] != body["session_id"]:
                raise ControlError("COMMAND_NOT_FOUND", 404)
            result = self.result(body["command_id"])
            if result["status"] != "queued":
                return result
            target = cmd["payload"]
            try:
                self._check(target, state)
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
                        )
                        no_op = effect_settings_equal(
                            raw, clip.effect_settings
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
            except ActionValidationError as exc:
                cmd["result"].update(status="rejected", error_code=exc.code)
            except Exception:
                cmd["result"].update(status="rejected", error_code="DATABASE_ERROR")
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
            self._session(identifier(body["session_id"]))
            cmd = self.commands.get(identifier(body["command_id"]))
            if cmd is None or cmd["payload"]["session_id"] != body["session_id"]:
                raise ControlError("COMMAND_NOT_FOUND", 404)
            if body["preview_status"] not in ("refresh_requested", "unavailable"):
                raise ControlError("INVALID_PAYLOAD", 400)
            if cmd["result"]["persisted"]:
                cmd["result"].update(
                    status="ui_applied",
                    ui_applied=True,
                    preview_status=body["preview_status"],
                )
            return self.result(body["command_id"])
