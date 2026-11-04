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
        "id": 123,
        "run_attempt": 1,
        "check_suite_id": 999,
        "path": ".github/workflows/ci.yml",
        "event": "pull_request",
        "head_sha": HEAD,
        "repository": {"full_name": REPO},
        "status": "completed",
        "conclusion": "success",
        "pull_requests": [
            {
                "number": 42,
                "head": copy.deepcopy(pr["head"]),
                "base": copy.deepcopy(pr["base"]),
            }
        ],
    }
    checks = [
        {
            "id": 456 + index,
            "check_suite": {"id": 999},
            "name": name,
            "head_sha": HEAD,
            "status": "completed",
            "conclusion": "success",
            "app": {"slug": "github-actions"},
            "pull_requests": copy.deepcopy(workflow["pull_requests"]),
            "workflow": copy.deepcopy(workflow),
            "details_url": f"https://github.com/{REPO}/actions/runs/123/job/{456 + index}",
        }
        for index, name in enumerate(policy.REQUIRED_CHECKS)
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
    for check in evidence["checks"]:
        check["workflow"]["pull_requests"][0]["head"]["ref"] = "hotfix/export"
        check["pull_requests"][0]["head"]["ref"] = "hotfix/export"


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
    root = f"https://api.github.com/repos/{REPO}"

    def __init__(self, evidence):
        self.evidence = evidence
        self.calls = []
        self.runs = [copy.deepcopy(evidence["checks"][0]["workflow"])]
        self.checks = copy.deepcopy(evidence["checks"])
        self.jobs = [
            {
                "id": c["id"],
                "name": c["name"],
                "run_id": 123,
                "run_attempt": 1,
                "head_sha": HEAD,
                "status": c["status"],
                "conclusion": c["conclusion"],
                "check_run_url": f"{self.root}/check-runs/{c['id']}",
            }
            for c in self.checks
        ]

    def get(self, path):
        self.calls.append(path)
        data = self.evidence
        if path.startswith("/actions/runs/"):
            return copy.deepcopy(
                next(r for r in self.runs if str(r["id"]) == path.rsplit("/", 1)[1])
            )
        if path.startswith("/check-runs/"):
            return copy.deepcopy(
                next(c for c in self.checks if str(c["id"]) == path.rsplit("/", 1)[1])
            )
        return copy.deepcopy(
            {
                "/pulls/42": data["current"],
                "/collaborators/maintainer/permission": {"permission": "write"},
                "/branches/develop": {"commit": {"sha": data["live_head"]}},
                "/branches/main": {"commit": {"sha": data["live_base"]}},
            }[path]
        )

    def pages(self, path, key=None):
        self.calls.append(path)
        if path.endswith("reviews"):
            return copy.deepcopy(self.evidence["reviews"])
        if key == "workflow_runs":
            assert "event=pull_request&head_sha=" in path
            return copy.deepcopy(self.runs)
        assert key == "jobs" and "/attempts/" in path
        return copy.deepcopy(self.jobs)


def test_collector_requeries_candidate_and_fetches_real_workflow(evidence):
    api = FakeAPI(evidence)
    assert policy.evaluate(api, evidence["expected"]) == [policy.PACKAGED_GATE_HOLD]
    assert api.calls.count("/pulls/42") == 2
    assert api.calls.count("/actions/runs/123") == 2
    assert "/actions/runs/123/attempts/1/jobs" in api.calls
    assert not any("/commits/" in call for call in api.calls)


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


def test_collector_ignores_same_sha_push_run(evidence):
    api = FakeAPI(evidence)
    api.runs.append(
        {
            **copy.deepcopy(api.runs[0]),
            "id": 124,
            "event": "push",
            "conclusion": "failure",
        }
    )
    assert policy.evaluate(api, evidence["expected"]) == [policy.PACKAGED_GATE_HOLD]


@pytest.mark.parametrize("state", ["queued", "in_progress", "failure", "stale_base"])
def test_newest_run_cannot_fall_back_to_old_green(evidence, state):
    api = FakeAPI(evidence)
    newer = copy.deepcopy(api.runs[0])
    newer["id"] = 124
    api.runs.append(newer)
    if state == "stale_base":
        newer["pull_requests"][0]["base"]["sha"] = "c" * 40
        with pytest.raises(ValueError, match="candidate"):
            policy.collect_checks(api, evidence["expected"])
    else:
        newer["status"] = state if state != "failure" else "completed"
        newer["conclusion"] = state if state == "failure" else None
        # No jobs in a newly queued run; no fallback to run 123's green checks.
        api.jobs = []
        checks = policy.collect_checks(api, evidence["expected"])
        evidence["checks"] = checks
        assert len(errors(evidence)) == 3


@pytest.mark.parametrize(
    "bad", ["attempt", "run", "suite", "check_id", "url", "check_base", "check_status"]
)
def test_collector_rejects_job_check_identity_mismatch(evidence, bad):
    api = FakeAPI(evidence)
    if bad == "attempt":
        api.jobs[0]["run_attempt"] = 2
    elif bad == "run":
        api.jobs[0]["run_id"] = 999
    elif bad == "suite":
        api.checks[0]["check_suite"]["id"] = 888
    elif bad == "check_id":
        api.jobs[0]["check_run_url"] = api.root + "/check-runs/not-an-id"
    elif bad == "url":
        api.jobs[0]["check_run_url"] = "https://other.invalid/check-runs/456"
    elif bad == "check_base":
        api.checks[0]["pull_requests"][0]["base"]["sha"] = "c" * 40
    else:
        api.checks[0]["status"] = "queued"
    with pytest.raises(ValueError):
        policy.collect_checks(api, evidence["expected"])


def test_partial_rerun_cannot_borrow_prior_attempt_jobs(evidence):
    api = FakeAPI(evidence)
    api.runs[0]["run_attempt"] = 2
    api.jobs = api.jobs[:1]
    api.jobs[0]["run_attempt"] = 2
    evidence["checks"] = policy.collect_checks(api, evidence["expected"])
    assert len(errors(evidence)) == 2
    assert "/actions/runs/123/attempts/2/jobs" in api.calls


@pytest.mark.parametrize("movement", ["attempt", "new_run", "review"])
def test_collector_detects_evidence_movement(evidence, monkeypatch, movement):
    api = FakeAPI(evidence)
    get, pages = api.get, api.pages

    def moving_get(path):
        result = get(path)
        if (
            path == "/actions/runs/123"
            and api.calls.count(path) == 2
            and movement == "attempt"
        ):
            result["run_attempt"] = 2
        return result

    def moving_pages(path, key=None):
        result = pages(path, key)
        if (
            key == "workflow_runs"
            and api.calls.count(path) == 2
            and movement == "new_run"
        ):
            result.append({**copy.deepcopy(result[0]), "id": 124})
        if (
            path.endswith("reviews")
            and api.calls.count(path) == 2
            and movement == "review"
        ):
            result[0]["state"] = "DISMISSED"
        return result

    monkeypatch.setattr(api, "get", moving_get)
    monkeypatch.setattr(api, "pages", moving_pages)
    if movement == "review":
        assert (
            "changed during evaluation" in policy.evaluate(api, evidence["expected"])[0]
        )
    else:
        with pytest.raises(ValueError, match="changed"):
            policy.collect_checks(api, evidence["expected"])


def test_real_github_snapshot_run_attempt_linkage():
    snapshot = json.loads(
        (ROOT / "tests/fixtures/main_admission_github.json").read_text(encoding="utf-8")
    )
    run = snapshot["run"]
    link = run["pull_requests"][0]
    pr = {
        "number": link["number"],
        "head": link["head"],
        "base": {**link["base"], "repo": run["repository"]},
    }

    class SnapshotAPI:
        root = "https://api.github.com/repos/Magehawks/orga-drone"

        def pages(self, path, key):
            if key == "workflow_runs":
                return [copy.deepcopy(run)]
            assert path == f"/actions/runs/{run['id']}/attempts/1/jobs"
            return copy.deepcopy(snapshot["jobs"])

        def get(self, path):
            if path == f"/actions/runs/{run['id']}":
                return copy.deepcopy(run)
            return copy.deepcopy(
                next(c for c in snapshot["checks"] if path == f"/check-runs/{c['id']}")
            )

    checks = policy.collect_checks(SnapshotAPI(), pr)
    assert {c["name"] for c in checks} == set(policy.REQUIRED_CHECKS)
    assert all(c["conclusion"] == "success" for c in checks)


@pytest.mark.parametrize(
    "labels", [[], [{"name": "admission:recheck"}], [{"name": "approved"}]]
)
def test_recheck_labels_never_authorize_admission(evidence, labels):
    evidence["current"]["labels"] = labels
    assert policy.admission_errors(**evidence) == [policy.PACKAGED_GATE_HOLD]


def test_query_pagination_preserves_filter_parameters(monkeypatch):
    api = policy.GitHub(REPO, "synthetic")
    paths = []

    def get(path):
        paths.append(path)
        return {
            "workflow_runs": [{}] * 100 if path.endswith("&page=1") else [],
            "total_count": 100,
        }

    monkeypatch.setattr(api, "get", get)
    assert (
        len(api.pages("/runs?event=pull_request&head_sha=abc", "workflow_runs")) == 100
    )
    assert paths == [
        "/runs?event=pull_request&head_sha=abc&per_page=100&page=1",
        "/runs?event=pull_request&head_sha=abc&per_page=100&page=2",
    ]


def test_counted_pagination_cannot_silently_truncate(monkeypatch):
    api = policy.GitHub(REPO, "synthetic")
    monkeypatch.setattr(api, "get", lambda path: {"total_count": 3, "jobs": []})
    with pytest.raises(ValueError, match="Incomplete metadata count"):
        api.pages("/jobs", "jobs")


def test_recheck_label_cannot_replace_approval(evidence):
    evidence["current"]["labels"] = [{"name": "admission:recheck"}]
    evidence["reviews"] = []
    assert any("approval" in message for message in errors(evidence))


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
    assert "ready_for_review, labeled, unlabeled]" in workflow
    assert "\n    if:" not in workflow and "continue-on-error:" not in workflow
    assert ": write" not in workflow
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "  pull_request:\n  push:\n    branches: [main, develop]" in ci
    for name in policy.REQUIRED_CHECKS:
        assert f"name: {name}" in ci
    assert "  workflow_dispatch:" in ci and "  workflow_call:" in ci
