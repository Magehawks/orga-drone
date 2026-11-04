"""Packaged Windows E2E evidence schema regressions."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "packaged_e2e", ROOT / "packaging/packaged_e2e.py"
)
assert SPEC is not None and SPEC.loader is not None
packaged_e2e = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packaged_e2e)

HEAD = "a" * 40
BASE = "b" * 40
MERGE = "c" * 40
TREE = "d" * 40
REPO = "example/drone"
DIGEST = "e" * 64


def _zip(evidence: dict[str, object]) -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("evidence.json", json.dumps(evidence))
    return payload.getvalue()


def _evidence() -> dict[str, object]:
    return {
        "schema": packaged_e2e.SCHEMA,
        "repository": REPO,
        "pr_number": 42,
        "head_sha": HEAD,
        "base_sha": BASE,
        "tested_merge_sha": MERGE,
        "tested_tree_sha": TREE,
        "run_id": 900,
        "run_attempt": 1,
        "artifact_name": packaged_e2e.artifact_names(1, HEAD)[0],
        "artifact_sha256": DIGEST,
        "artifact_size": 1234,
        "app_version": "2.3.3",
        "webview2_version": "156.0.4314.50",
        "runner_image": "Windows Server 2025",
        "generated_at": "2026-11-04T11:00:00+00:00",
        "result": "pass",
        "manual_checks_claimed": False,
        "journeys": {
            name: {"ok": True, "elapsed_ms": 1}
            for name in packaged_e2e.REQUIRED_JOURNEYS
        },
    }


def _check(evidence: dict[str, object]) -> list[str]:
    return packaged_e2e.evidence_errors(
        evidence,
        repository=REPO,
        pr_number=42,
        head_sha=HEAD,
        base_sha=BASE,
        merge_sha=MERGE,
        tree_sha=TREE,
        run_id=900,
        run_attempt=1,
        app_artifact_name=packaged_e2e.artifact_names(1, HEAD)[0],
        app_artifact_digest=DIGEST,
        app_artifact_size=1234,
    )


def test_valid_evidence_has_no_errors():
    assert _check(_evidence()) == []


@pytest.mark.parametrize(
    "field",
    [
        "schema",
        "repository",
        "pr_number",
        "head_sha",
        "base_sha",
        "tested_merge_sha",
        "tested_tree_sha",
        "run_id",
        "run_attempt",
        "artifact_name",
        "artifact_sha256",
        "artifact_size",
        "app_version",
        "webview2_version",
        "runner_image",
        "generated_at",
        "result",
    ],
)
def test_every_binding_field_is_required(field):
    evidence = _evidence()
    evidence.pop(field)
    assert _check(evidence)


def test_manual_checks_must_not_be_claimed():
    evidence = _evidence()
    evidence["manual_checks_claimed"] = True
    assert _check(evidence)


def test_missing_or_failed_journey_is_rejected():
    evidence = _evidence()
    journeys = evidence["journeys"]
    assert isinstance(journeys, dict)
    journeys["export"] = {"ok": False}
    assert any("export" in error for error in _check(evidence))
    journeys.pop("export")
    assert any("export" in error for error in _check(evidence))


def test_extra_journeys_are_allowed_but_required_set_is_not():
    evidence = _evidence()
    journeys = evidence["journeys"]
    assert isinstance(journeys, dict)
    journeys["future_journey"] = {"ok": True}
    assert _check(evidence) == []


def test_digest_prefix_and_case_are_normalized():
    evidence = _evidence()
    evidence["artifact_sha256"] = "sha256:" + DIGEST.upper()
    assert _check(evidence) == []


def test_zip_must_contain_only_evidence_json():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("evidence.json", json.dumps(_evidence()))
        archive.writestr("extra.txt", "unexpected")
    with pytest.raises(ValueError, match="only evidence.json"):
        packaged_e2e.parse_evidence_zip(payload.getvalue())


def test_zip_must_be_json_object():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("evidence.json", "[]")
    with pytest.raises(ValueError, match="object"):
        packaged_e2e.parse_evidence_zip(payload.getvalue())


def test_zip_size_limit():
    payload = b"x" * (packaged_e2e.MAX_EVIDENCE_ZIP_BYTES + 1)
    with pytest.raises(ValueError, match="too large"):
        packaged_e2e.parse_evidence_zip(payload)


def test_artifact_name_includes_attempt_and_head():
    app, evidence = packaged_e2e.artifact_names(3, HEAD)
    assert app == f"orga-drone-windows-e2e-3-{HEAD}"
    assert evidence == f"windows-e2e-evidence-3-{HEAD}"


def test_evidence_zip_roundtrip():
    evidence = copy.deepcopy(_evidence())
    payload = _zip(evidence)
    assert hashlib.sha256(payload).digest()
    assert packaged_e2e.parse_evidence_zip(payload) == evidence
