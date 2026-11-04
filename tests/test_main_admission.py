"""Main admission never passes before real issue #262 evidence is implemented."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "main_admission", ROOT / "packaging/main_admission.py"
)
assert SPEC is not None and SPEC.loader is not None
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)
HEAD, BASE = "a" * 40, "b" * 40
REPO = "example/drone"


@pytest.fixture
def evidence():
    pr = {
        "number": 42,
        "state": "open",
        "draft": False,
        "body": "",
        "user": {"login": "author"},
        "head": {"sha": HEAD, "ref": "develop", "repo": {"full_name": REPO}},
        "base": {"sha": BASE, "ref": "main", "repo": {"full_name": REPO}},
    }
    review = {
        "id": 1,
        "state": "APPROVED",
        "commit_id": HEAD,
        "user": {"login": "maintainer", "type": "User"},
        "body": f"Main admission candidate: {HEAD} {BASE}",
    }
    workflow = {
        "path": ".github/workflows/ci.yml",
        "event": "pull_request",
        "head_sha": HEAD,
        "repository": {"full_name": REPO},
    }
    checks = [
        {
            "name": name,
            "head_sha": HEAD,
            "status": "completed",
            "conclusion": "success",
            "app": {"slug": "github-actions"},
            "pull_requests": [{"number": 42}],
            "workflow": copy.deepcopy(workflow),
            "details_url": f"https://github.com/{REPO}/actions/runs/123/job/456",
        }
        for name in policy.REQUIRED_CHECKS
    ]
    return {
        "expected": copy.deepcopy(pr),
        "current": pr,
        "live_head": HEAD,
        "live_base": BASE,
        "reviews": [review],
        "permissions": {"maintainer": "write"},
        "checks": checks,
        "emergency_issue": None,
    }


def errors(evidence):
    result = policy.admission_errors(**evidence)
    assert result[-1] == policy.PACKAGED_GATE_HOLD
    return result[:-1]


def hotfix(evidence):
    for key in ("expected", "current"):
        evidence[key]["head"]["ref"] = "hotfix/export"
    evidence["current"]["body"] = (
        "Emergency issue: #12\nEmergency reason: Broken export\nEmergency scope: Export fix"
    )
    evidence["emergency_issue"] = {"body": "Urgent regression; export-only scope."}


@pytest.mark.parametrize("use_hotfix", [False, True])
def test_otherwise_eligible_candidate_still_denied(evidence, use_hotfix):
    if use_hotfix:
        hotfix(evidence)
    assert errors(evidence) == []
    assert policy.admission_errors(**evidence) == [policy.PACKAGED_GATE_HOLD]


@pytest.mark.parametrize(
    "branch", ["main", "feature/foo", "hotfix/", "Develop", "release/next"]
)
def test_invalid_source_branch(evidence, branch):
    evidence["expected"]["head"]["ref"] = branch
    evidence["current"]["head"]["ref"] = branch
    assert any("eligible" in e for e in errors(evidence))


def test_fork_and_draft_rejected(evidence):
    evidence["current"]["head"]["repo"]["full_name"] = "fork/drone"
    evidence["current"]["draft"] = True
    assert any("eligible" in e for e in errors(evidence))


@pytest.mark.parametrize(
    "missing", ["issue", "reason", "scope", "existing_issue", "issue_body"]
)
def test_hotfix_requires_documented_emergency(evidence, missing):
    hotfix(evidence)
    if missing == "existing_issue":
        evidence["emergency_issue"] = None
    elif missing == "issue_body":
        evidence["emergency_issue"] = {"body": ""}
    else:
        evidence["current"]["body"] = "\n".join(
            line
            for line in evidence["current"]["body"].splitlines()
            if not line.startswith(f"Emergency {missing}:")
        )
    assert any("Hotfix" in e for e in errors(evidence))


@pytest.mark.parametrize(
    "invalid",
    ["missing", "permission", "bot", "self", "head", "base", "dismissed", "changes"],
)
def test_missing_untrusted_or_stale_approval(evidence, invalid):
    review = evidence["reviews"][0]
    if invalid == "missing":
        evidence["reviews"] = []
    elif invalid == "permission":
        evidence["permissions"] = {"maintainer": "read"}
    elif invalid == "bot":
        review["user"]["type"] = "Bot"
    elif invalid == "self":
        evidence["current"]["user"]["login"] = "maintainer"
    elif invalid == "head":
        review["commit_id"] = "c" * 40
    elif invalid == "base":
        review["body"] = f"Main admission candidate: {HEAD} {'c' * 40}"
    else:
        evidence["reviews"].append(
            {
                **review,
                "id": 2,
                "state": "DISMISSED" if invalid == "dismissed" else "CHANGES_REQUESTED",
            }
        )
    assert any("approval" in e for e in errors(evidence))


@pytest.mark.parametrize(
    "conclusion",
    ["skipped", "neutral", "failure", "cancelled", "timed_out", "stale", None],
)
def test_non_success_checks_rejected(evidence, conclusion):
    evidence["checks"][0]["conclusion"] = conclusion
    assert any(policy.REQUIRED_CHECKS[0] in e for e in errors(evidence))


@pytest.mark.parametrize(
    "invalid",
    ["missing", "duplicate", "sha", "app", "pr", "running", "workflow", "push"],
)
def test_missing_stale_or_spoofed_checks(evidence, invalid):
    check = evidence["checks"][0]
    if invalid == "missing":
        evidence["checks"].pop(0)
    elif invalid == "duplicate":
        evidence["checks"].append(copy.deepcopy(check))
    elif invalid == "sha":
        check["head_sha"] = "c" * 40
    elif invalid == "app":
        check["app"]["slug"] = "other-app"
    elif invalid == "pr":
        check["pull_requests"] = []
    elif invalid == "running":
        check["status"] = "in_progress"
    elif invalid == "workflow":
        check["workflow"]["path"] = ".github/workflows/spoof.yml"
    else:
        check["workflow"]["event"] = "push"
    assert any(policy.REQUIRED_CHECKS[0] in e for e in errors(evidence))


def test_push_checks_cannot_replace_or_veto_verified_pr_checks(evidence):
    push = copy.deepcopy(evidence["checks"][0])
    push["workflow"]["event"] = "push"
    push["conclusion"] = "failure"
    evidence["checks"].append(push)
    assert errors(evidence) == []
    evidence["checks"].pop(0)
    assert any(policy.REQUIRED_CHECKS[0] in e for e in errors(evidence))


@pytest.mark.parametrize("which", ["head", "base", "live_head", "live_base"])
def test_candidate_movement_rejected(evidence, which):
    if which.startswith("live_"):
        evidence[which] = "c" * 40
    else:
        evidence["current"][which]["sha"] = "c" * 40
    assert any("Stale candidate" in e for e in errors(evidence))


class FakeAPI:
    def __init__(self, evidence):
        self.evidence = evidence
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        data = self.evidence
        return copy.deepcopy(
            {
                "/pulls/42": data["current"],
                "/collaborators/maintainer/permission": {"permission": "write"},
                "/branches/develop": {"commit": {"sha": data["live_head"]}},
                "/branches/main": {"commit": {"sha": data["live_base"]}},
                "/actions/runs/123": data["checks"][0]["workflow"],
            }[path]
        )

    def pages(self, path, key=None):
        return copy.deepcopy(
            self.evidence["reviews"]
            if path.endswith("reviews")
            else self.evidence["checks"]
        )


def test_collector_requeries_candidate_and_fetches_real_workflow(evidence):
    api = FakeAPI(evidence)
    assert policy.evaluate(api, evidence["expected"]) == [policy.PACKAGED_GATE_HOLD]
    assert api.calls.count("/pulls/42") == 2
    assert api.calls.count("/actions/runs/123") == 1


def test_collector_detects_metadata_change(evidence, monkeypatch):
    api = FakeAPI(evidence)
    original_get = api.get

    def moving_get(path):
        result = original_get(path)
        if path == "/pulls/42" and api.calls.count(path) == 2:
            result["body"] = "Changed during evaluation"
        return result

    monkeypatch.setattr(api, "get", moving_get)
    assert "changed during evaluation" in policy.evaluate(api, evidence["expected"])[0]


@pytest.mark.parametrize("bad", ["api", "malformed"])
def test_cli_denies_api_or_malformed_metadata_without_secret_output(
    evidence, monkeypatch, tmp_path, capsys, bad
):
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps({"pull_request": evidence["expected"]}), encoding="utf-8"
    )
    for key, value in {
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_REPOSITORY": REPO,
        "GH_TOKEN": "synthetic-secret",
    }.items():
        monkeypatch.setenv(key, value)
    if bad == "api":

        def fail(*args):
            raise OSError("synthetic-secret")

        monkeypatch.setattr(policy.GitHub, "get", fail)
    else:
        event.write_text('{"pull_request": {}}', encoding="utf-8")
    assert policy.main() == 1
    output = capsys.readouterr().err
    assert "admission denied" in output
    assert "synthetic-secret" not in output


def test_pagination_never_silently_truncates(monkeypatch):
    api = policy.GitHub(REPO, "synthetic")
    monkeypatch.setattr(api, "get", lambda path: [{}] * 100)
    with pytest.raises(ValueError, match="pagination"):
        api.pages("/pulls/42/reviews")


def test_workflow_uses_base_policy_and_ci_preserves_pr_checks():
    workflow = (ROOT / ".github/workflows/main-admission.yml").read_text(
        encoding="utf-8"
    )
    assert "  pull_request:\n    branches: [main]" in workflow
    assert "pull_request_target:" not in workflow
    assert "ref: ${{ github.event.pull_request.base.sha }}" in workflow
    assert "persist-credentials: false" in workflow
    assert "name: Main admission policy" in workflow
    assert "python packaging/main_admission.py" in workflow
    assert ": write" not in workflow
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "  pull_request:\n  push:\n    branches: [main, develop]" in ci
    for name in policy.REQUIRED_CHECKS:
        assert f"name: {name}" in ci
    assert "  workflow_dispatch:" in ci and "  workflow_call:" in ci
