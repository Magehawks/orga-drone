"""Packaged Windows E2E evidence schema and validation for main admission.

The E2E workflow produces a small ``evidence.json`` artifact next to the
packaged zip. Admission validates the shape and candidate binding here; GitHub
run/artifact identity is checked separately by the read-only admission client.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Any

SCHEMA = "orga-drone-packaged-e2e-v1"
APP_ARTIFACT_PREFIX = "orga-drone-windows-e2e"
EVIDENCE_ARTIFACT_PREFIX = "windows-e2e-evidence"
REQUIRED_JOURNEYS = (
    "startup",
    "media_import",
    "library_navigation",
    "studio_open",
    "playback",
    "edit_persistence",
    "export",
    "source_integrity",
    "relaunch_persistence",
)
MAX_EVIDENCE_ZIP_BYTES = 16 * 1024 * 1024
MAX_EVIDENCE_JSON_BYTES = 256 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def artifact_names(run_attempt: int, head_sha: str) -> tuple[str, str]:
    """Return (app artifact, evidence artifact) names for one run attempt."""
    suffix = f"{run_attempt}-{head_sha}"
    return (
        f"{APP_ARTIFACT_PREFIX}-{suffix}",
        f"{EVIDENCE_ARTIFACT_PREFIX}-{suffix}",
    )


def sha256_hex(value: str) -> str:
    return (
        value[len("sha256:") :] if value.startswith("sha256:") else value
    ).lower()


def parse_evidence_zip(payload: bytes) -> dict[str, Any]:
    """Read exactly one ``evidence.json`` member from an Actions artifact zip."""
    if len(payload) > MAX_EVIDENCE_ZIP_BYTES:
        raise ValueError("Evidence artifact is too large")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValueError("Evidence artifact is not a zip file") from exc
    with archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if names != ["evidence.json"]:
            raise ValueError("Evidence artifact must contain only evidence.json")
        info = archive.getinfo("evidence.json")
        if info.file_size > MAX_EVIDENCE_JSON_BYTES:
            raise ValueError("Evidence JSON is too large")
        try:
            evidence = json.loads(archive.read(info))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("Evidence JSON is invalid") from exc
    if not isinstance(evidence, dict):
        raise ValueError("Evidence JSON must be an object")
    return evidence


def _string(evidence: dict[str, Any], key: str) -> str:
    value = evidence.get(key)
    return value if isinstance(value, str) else ""


def _int(evidence: dict[str, Any], key: str) -> int | None:
    value = evidence.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def evidence_errors(
    evidence: dict[str, Any],
    *,
    repository: str,
    pr_number: int,
    head_sha: str,
    base_sha: str,
    merge_sha: str,
    tree_sha: str,
    run_id: int,
    run_attempt: int,
    app_artifact_name: str,
) -> list[str]:
    """Return every reason the evidence does not bind to this candidate."""
    errors: list[str] = []
    if _string(evidence, "schema") != SCHEMA:
        errors.append("Wrong packaged E2E evidence schema.")
    if _string(evidence, "repository") != repository:
        errors.append("Packaged E2E repository mismatch.")
    if _int(evidence, "pr_number") != pr_number:
        errors.append("Packaged E2E pull request mismatch.")
    if _string(evidence, "head_sha") != head_sha:
        errors.append("Packaged E2E head SHA mismatch.")
    if _string(evidence, "base_sha") != base_sha:
        errors.append("Packaged E2E base SHA mismatch.")
    if _string(evidence, "tested_merge_sha") != merge_sha:
        errors.append("Packaged E2E merge SHA mismatch.")
    if _string(evidence, "tested_tree_sha") != tree_sha:
        errors.append("Packaged E2E tree mismatch.")
    if _int(evidence, "run_id") != run_id or _int(evidence, "run_attempt") != run_attempt:
        errors.append("Packaged E2E workflow run/attempt mismatch.")
    if _string(evidence, "artifact_name") != app_artifact_name:
        errors.append("Packaged E2E artifact name mismatch.")
    if not _COMMIT_RE.fullmatch(_string(evidence, "head_sha")):
        errors.append("Packaged E2E head SHA is not a commit SHA.")
    if not _COMMIT_RE.fullmatch(_string(evidence, "base_sha")):
        errors.append("Packaged E2E base SHA is not a commit SHA.")
    if not _COMMIT_RE.fullmatch(_string(evidence, "tested_merge_sha")):
        errors.append("Packaged E2E merge SHA is not a commit SHA.")
    if not _COMMIT_RE.fullmatch(_string(evidence, "tested_tree_sha")):
        errors.append("Packaged E2E tree is not a Git tree SHA.")
    size = _int(evidence, "artifact_size")
    if size is None or size <= 0:
        errors.append("Packaged E2E artifact size is missing or invalid.")
    if not _SHA256_RE.fullmatch(sha256_hex(_string(evidence, "artifact_sha256"))):
        errors.append("Packaged E2E artifact digest is invalid.")
    if evidence.get("result") != "pass":
        errors.append("Packaged E2E did not report a pass.")
    if evidence.get("manual_checks_claimed") is not False:
        errors.append("Packaged E2E must not claim manual/MOTW checks.")
    for key in ("app_version", "webview2_version", "runner_image", "generated_at"):
        if not _string(evidence, key):
            errors.append(f"Packaged E2E evidence is missing {key}.")
    journeys = evidence.get("journeys")
    if not isinstance(journeys, dict):
        errors.append("Packaged E2E journey results are missing.")
    else:
        for name in REQUIRED_JOURNEYS:
            result = journeys.get(name)
            if not isinstance(result, dict) or result.get("ok") is not True:
                errors.append(f"Packaged E2E journey failed or is missing: {name}")
    return errors
