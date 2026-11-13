"""Canonical grade persistence, write guards, and legacy wrapping (#351).

Backup/restore helpers live in ``grade_backup``. This module enables first
canonical writes only after a verified pre-upgrade backup exists. Legacy color
setters must call ``grade_write_guard`` so they cannot mutate ignored fields on
canonical clips.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any, Mapping

from orga_drone.grade_backup import (
    BACKUP_DIR_NAME,
    LIVE_DB_NAME,
    GradeBackupError,
    backup_directory,
    create_backup,
    verify_backup,
)
from orga_drone.studio_grade_contract import LEGACY_KEYS, fail, snapshot
from orga_drone.studio_grade_model import GradeModel, read_grade

WRITES_MARKER = "canonical-writes-enabled.json"


def is_canonical_effect_settings(raw: str | None) -> bool:
    """True when effect_settings already carries a validated grade envelope."""
    try:
        return read_grade(raw).authority == "canonical"
    except Exception:
        # Corrupt canonical JSON must not be overwritten by legacy dumpers.
        try:
            data = json.loads(raw or "{}")
        except (ValueError, TypeError):
            return False
        return isinstance(data, dict) and "grade" in data


def grade_write_guard(raw: str | None) -> None:
    """Reject legacy color writers when a canonical grade is authoritative."""
    if not is_canonical_effect_settings(raw):
        return
    fail(
        "grade",
        "Legacy color writers cannot mutate a canonical grade",
        "CANONICAL_GUARD",
    )


def _new_step_id() -> str:
    return f"step-{secrets.token_hex(8)}"


def wrap_legacy_to_canonical(
    raw: str | None,
    *,
    revision: int = 1,
) -> dict[str, Any]:
    """Wrap legacy color keys into ``legacy-stack-v1`` without rendering changes.

    Non-color effect keys stay at the root. Legacy color keys move into the
    single stack params object and are removed from the root. Missing color
    sections stay absent (plan evaluation materializes reader defaults).
    """
    model = read_grade(raw)
    if model.authority == "canonical":
        fail("grade", "Clip is already canonical", "UNSUPPORTED_GRADE")
    try:
        data = json.loads(raw or "{}")
    except (ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    params: dict[str, Any] = {}
    for key in LEGACY_KEYS:
        if key in data:
            params[key] = data.pop(key)
    grade = {
        "schema_version": 1,
        "evaluator": "legacy-v1",
        "revision": int(revision),
        "input": {"profile": "legacy-native", "technical_lut": None},
        "working": "legacy-native",
        "steps": [
            {
                "id": _new_step_id(),
                "type": "legacy-stack-v1",
                "enabled": True,
                "mix": 1,
                "selection_id": None,
                "params": params,
            }
        ],
        "selections": [],
        "animation": [],
        "output": {"profile": "legacy-native", "gamut": "legacy"},
        "extensions": {},
    }
    data["grade"] = grade
    # Validate before returning so callers never persist an invalid envelope.
    return read_grade(data).to_dict()


def allocate_revision(current: GradeModel) -> int:
    """Next monotonic revision for an accepted canonical edit."""
    return int(current.revision) + 1


def publish_grade_document(
    current: GradeModel,
    proposed: Mapping[str, Any] | GradeModel,
    *,
    expected_revision: int,
) -> str:
    """Validate a proposed document, bump revision, and return stored JSON text."""
    if current.authority != "canonical":
        fail(
            "grade",
            "Legacy clips require an explicit wrap before canonical edits",
            "UNSUPPORTED_GRADE",
        )
    if int(expected_revision) != int(current.revision):
        fail("grade.revision", "Grade revision conflict", "STALE_REVISION")
    document = (
        proposed.to_dict()
        if isinstance(proposed, GradeModel)
        else dict(proposed)
    )
    grade = document.get("grade")
    if not isinstance(grade, dict):
        fail("grade", "Proposed document is missing grade")
    grade = dict(grade)
    grade["revision"] = allocate_revision(current)
    document = dict(document)
    document["grade"] = grade
    published = read_grade(document)
    if published.authority != "canonical":
        fail("grade", "Proposed document is not canonical", "INVALID_GRADE")
    return snapshot(published.to_dict())


def writes_enabled(data_dir: Path) -> bool:
    marker = Path(data_dir) / BACKUP_DIR_NAME / WRITES_MARKER
    return marker.is_file()


def _mark_writes_enabled(data_dir: Path, *, app_version: str, backup: Mapping[str, Any]) -> None:
    marker = Path(data_dir) / BACKUP_DIR_NAME / WRITES_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": 1,
        "app_version": app_version,
        "backup_sha256": backup.get("sha256"),
        "backup_bytes": backup.get("bytes"),
        "warning": "Restoring the pre-grade backup discards later edits.",
    }
    temporary = marker.with_name(marker.name + ".partial")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(marker)


def startup_backup_if_needed(data_dir: Path, *, app_version: str) -> dict[str, Any] | None:
    """Ensure a verified pre-upgrade backup exists before canonical writes.

    Returns the manifest when a backup is present or newly created. Missing
    live databases skip backup and leave writes disabled until a library exists.
    """
    data_dir = Path(data_dir)
    live = data_dir / LIVE_DB_NAME
    if not live.is_file():
        return None
    directory = backup_directory(data_dir)
    backup_file = directory / LIVE_DB_NAME
    manifest_path = directory / "manifest.json"
    if backup_file.is_file() and manifest_path.is_file():
        try:
            manifest = verify_backup(directory)
        except GradeBackupError:
            manifest = None
        if manifest is not None:
            if not writes_enabled(data_dir):
                _mark_writes_enabled(data_dir, app_version=app_version, backup=manifest)
            return dict(manifest)
    manifest = create_backup(live, directory, app_version=app_version)
    _mark_writes_enabled(data_dir, app_version=app_version, backup=manifest)
    return dict(manifest)


def require_writes_enabled(data_dir: Path) -> None:
    if not writes_enabled(data_dir):
        fail(
            "grade",
            "Canonical grade writes require a verified pre-upgrade backup",
            "UNSUPPORTED_GRADE",
        )


def convert_legacy_to_managed(
    raw: str | None,
    *,
    revision: int = 1,
    acknowledge_appearance_change: bool = False,
) -> dict[str, Any]:
    """Create a neutral managed-sdr grade. Appearance may change vs legacy.

    This does not invent a pixel-identical translation of YUV eq. Callers must
    pass ``acknowledge_appearance_change=True``. Legacy color keys are retained
    only inside ``extensions.legacy_recovery`` for rollback evidence.
    """
    if not acknowledge_appearance_change:
        fail(
            "grade",
            "Managed conversion requires explicit appearance-change acknowledgement",
            "UNSUPPORTED_GRADE",
        )
    model = read_grade(raw)
    recovery: dict[str, Any] = {}
    if model.authority == "canonical":
        if model.evaluator == "managed-sdr-v1":
            fail("grade", "Clip is already managed-sdr", "UNSUPPORTED_GRADE")
        grade = model.grade
        assert grade is not None
        step = grade["steps"][0] if grade.get("steps") else None
        if isinstance(step, dict):
            recovery = dict(step.get("params") or {})
        document = model.to_dict()
    else:
        try:
            data = json.loads(raw or "{}")
        except (ValueError, TypeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        for key in LEGACY_KEYS:
            if key in data:
                recovery[key] = data.pop(key)
        document = data
    document["grade"] = {
        "schema_version": 1,
        "evaluator": "managed-sdr-v1",
        "revision": int(revision),
        "input": {"profile": "srgb", "technical_lut": None},
        "working": "linear-bt709",
        "steps": [],
        "selections": [],
        "animation": [],
        "output": {"profile": "bt709-sdr", "gamut": "clip"},
        "extensions": {"legacy_recovery": recovery},
    }
    return read_grade(document).to_dict()
