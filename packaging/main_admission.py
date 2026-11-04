"""Read-only main admission guard. No candidate can pass before issue #262.

Only GitHub metadata is read. No PR code, artifacts, labels, or supplied gate
results can enable admission. The workflow executes this file from its base SHA.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote

REQUIRED_CHECKS = (
    "Ruff, MyPy and unit tests",
    "JavaScript lint, format and tests",
    "App journey smoke",
)
PACKAGED_GATE_HOLD = (
    "Issue #262 packaged Windows E2E/manual gate is unavailable; admission denied."
)


def candidate(pr: dict[str, Any]) -> tuple[str, str]:
    return pr["head"]["sha"], pr["base"]["sha"]


def admission_errors(
    expected: dict[str, Any],
    current: dict[str, Any],
    live_head: str,
    live_base: str,
    reviews: list[dict[str, Any]],
    permissions: dict[str, str],
    checks: list[dict[str, Any]],
    emergency_issue: dict[str, Any] | None,
) -> list[str]:
    """Diagnose necessary conditions, then unconditionally apply the #262 hold."""
    errors = []
    head, base = candidate(expected)
    repo = expected["base"]["repo"]["full_name"]
    branch = expected["head"]["ref"]
    if (
        current["state"] != "open"
        or current["draft"]
        or current["base"]["ref"] != "main"
        or current["base"]["repo"]["full_name"] != repo
        or current["head"]["repo"]["full_name"] != repo
        or expected["head"]["repo"]["full_name"] != repo
        or current["head"]["ref"] != branch
        or not (
            branch == "develop"
            or re.fullmatch(r"hotfix/[A-Za-z0-9][A-Za-z0-9._/-]*", branch)
        )
    ):
        errors.append(
            "Only open, non-draft same-repository develop or documented hotfix PRs to main are eligible."
        )
    if candidate(current) != (head, base) or (live_head, live_base) != (head, base):
        errors.append(
            "Stale candidate: head or base changed; refresh validation and approval."
        )

    body = current.get("body") or ""
    if branch.startswith("hotfix/") and (
        re.search(r"(?m)^Emergency issue: #[1-9][0-9]*\s*$", body) is None
        or re.search(r"(?m)^Emergency reason: \S.+$", body) is None
        or re.search(r"(?m)^Emergency scope: \S.+$", body) is None
        or not emergency_issue
        or emergency_issue.get("pull_request")
        or not emergency_issue.get("body", "").strip()
    ):
        errors.append(
            "Hotfix needs an existing issue, emergency reason, and narrow scope in the PR."
        )

    # Comments do not revoke approval; a later decisive review does.
    latest: dict[str, dict[str, Any]] = {}
    for review in sorted(reviews, key=lambda item: item["id"]):
        if review["state"] in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            latest[review["user"]["login"]] = review
    marker = f"Main admission candidate: {head} {base}"
    if not any(
        review["state"] == "APPROVED"
        and review["commit_id"] == head
        and review["user"]["type"] == "User"
        and login != current["user"]["login"]
        and permissions.get(login) in {"write", "maintain", "admin"}
        and marker in (review.get("body") or "").splitlines()
        for login, review in latest.items()
    ):
        errors.append(
            "Missing independent human approval for this exact head/base from a maintainer with write access."
            " Solo-owner PRs need the approval-profile decision documented in BRANCH_MIGRATION.md before activation."
        )

    for name in REQUIRED_CHECKS:
        # Push CI on develop can share the head and names with PR CI. Only a
        # verified PR run is evidence; push runs must neither satisfy nor veto it.
        matching = [
            check
            for check in checks
            if check["name"] == name and check["workflow"]["event"] == "pull_request"
        ]
        # Reject ambiguity as well as wrong provenance; never accept a spoofed name.
        if len(matching) != 1 or not all(
            check["head_sha"] == head
            and check["status"] == "completed"
            and check["conclusion"] == "success"
            and check["app"]["slug"] == "github-actions"
            and any(pr["number"] == current["number"] for pr in check["pull_requests"])
            and check["workflow"]["path"] == ".github/workflows/ci.yml"
            and check["workflow"]["event"] == "pull_request"
            and check["workflow"]["head_sha"] == head
            and check["workflow"]["repository"]["full_name"] == repo
            and check["workflow"]["status"] == "completed"
            and check["workflow"]["conclusion"] == "success"
            and linked_candidate(check["workflow"], current)
            for check in matching
        ):
            errors.append(
                f"Missing, ambiguous, stale, untrusted, or unsuccessful check: {name}"
            )

    # Deliberately no success branch, enable flag, or fake #262 evidence schema.
    errors.append(PACKAGED_GATE_HOLD)
    return errors


class GitHub:
    def __init__(self, repo: str, token: str):
        if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) is None:
            raise ValueError("Invalid repository")
        self.root = f"https://api.github.com/repos/{repo}"
        self.token = token

    def get(self, path: str) -> Any:
        request = urllib.request.Request(
            self.root + path,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    def pages(self, path: str, key: str | None = None) -> list[dict[str, Any]]:
        result = []
        total = None
        for page in range(1, 11):
            separator = "&" if "?" in path else "?"
            data = self.get(f"{path}{separator}per_page=100&page={page}")
            items = data[key] if key else data
            if key:
                reported = data["total_count"]
                if (
                    not isinstance(reported, int)
                    or reported < 0
                    or total not in (None, reported)
                ):
                    raise ValueError("Changing or invalid metadata count")
                total = reported
            if not isinstance(items, list):
                raise ValueError("Invalid paginated metadata")
            result.extend(items)
            if len(items) < 100:
                if total is not None and len(result) != total:
                    raise ValueError("Incomplete metadata count")
                return result
        raise ValueError("Incomplete metadata: pagination limit reached")


def linked_candidate(run: dict[str, Any], pr: dict[str, Any]) -> bool:
    return any(
        link["number"] == pr["number"]
        and link["head"]["sha"] == pr["head"]["sha"]
        and link["head"]["ref"] == pr["head"]["ref"]
        and link["base"]["sha"] == pr["base"]["sha"]
        and link["base"]["ref"] == "main"
        for link in run["pull_requests"]
    )


def newest_ci_run(api: GitHub, pr: dict[str, Any]) -> dict[str, Any]:
    head = pr["head"]["sha"]
    runs = api.pages(
        f"/actions/workflows/ci.yml/runs?event=pull_request&head_sha={head}",
        "workflow_runs",
    )
    # Choose before validating base/status. A newer stale/incomplete/failed run
    # must not cause fallback to an older green run for the same PR/head.
    matching = [
        run
        for run in runs
        if run["event"] == "pull_request"
        and run["head_sha"] == head
        and any(link["number"] == pr["number"] for link in run["pull_requests"])
    ]
    if not matching:
        raise ValueError("Missing PR CI run")
    return max(matching, key=lambda run: run["id"])


def collect_checks(api: GitHub, pr: dict[str, Any]) -> list[dict[str, Any]]:
    """Use one explicit workflow run/attempt, never commit-wide filter=latest."""
    selected = newest_ci_run(api, pr)
    run = api.get(f"/actions/runs/{selected['id']}")
    repo = pr["base"]["repo"]["full_name"]
    if (
        run["id"] != selected["id"]
        or run["path"] != ".github/workflows/ci.yml"
        or run["event"] != "pull_request"
        or run["head_sha"] != pr["head"]["sha"]
        or run["repository"]["full_name"] != repo
        or not linked_candidate(run, pr)
        or not isinstance(run["run_attempt"], int)
        or run["run_attempt"] < 1
    ):
        raise ValueError("Unverified CI run/candidate")
    attempt = run["run_attempt"]
    jobs = api.pages(f"/actions/runs/{run['id']}/attempts/{attempt}/jobs", "jobs")
    checks = []
    for job in jobs:
        if job["name"] not in REQUIRED_CHECKS:
            continue
        prefix = f"{api.root}/check-runs/"
        if not job["check_run_url"].startswith(prefix):
            raise ValueError("Untrusted check URL")
        check_id = job["check_run_url"][len(prefix) :]
        if not check_id.isdecimal():
            raise ValueError("Invalid check ID")
        check = api.get(f"/check-runs/{check_id}")
        if (
            job["run_id"] != run["id"]
            or job["run_attempt"] != attempt
            or job["head_sha"] != run["head_sha"]
            or check["id"] != int(check_id)
            or check["check_suite"]["id"] != run["check_suite_id"]
            or check["name"] != job["name"]
            or check["status"] != job["status"]
            or check["conclusion"] != job["conclusion"]
            or check["details_url"]
            != f"https://github.com/{repo}/actions/runs/{run['id']}/job/{job['id']}"
            or not linked_candidate(check, pr)
        ):
            raise ValueError("Unverified CI job/check linkage")
        check["workflow"] = run
        checks.append(check)
    # A partial rerun cannot borrow successes from an earlier attempt. Also
    # reject a run/attempt or newest-run change while collecting its evidence.
    if (
        api.get(f"/actions/runs/{run['id']}") != run
        or newest_ci_run(api, pr)["id"] != run["id"]
    ):
        raise ValueError("CI run/attempt changed during collection")
    return checks


def evaluate(api: GitHub, expected: dict[str, Any]) -> list[str]:
    number = expected["number"]
    current = api.get(f"/pulls/{number}")
    reviews = api.pages(f"/pulls/{number}/reviews")
    permissions = {
        login: api.get(f"/collaborators/{quote(login, safe='')}/permission")[
            "permission"
        ]
        for login in {
            r["user"]["login"]
            for r in reviews
            if r["state"] == "APPROVED" and r["user"]["type"] == "User"
        }
    }
    checks = collect_checks(api, expected)
    issue_match = re.search(
        r"(?m)^Emergency issue: #([1-9][0-9]*)\s*$", current.get("body") or ""
    )
    issue = api.get(f"/issues/{issue_match[1]}") if issue_match else None
    # Re-read after collecting evidence, including real branch tips: PR base.sha
    # can lag the live branch. Any movement or metadata/API failure denies.
    final = api.get(f"/pulls/{number}")
    if current != final or api.pages(f"/pulls/{number}/reviews") != reviews:
        return [
            "PR/review metadata changed during evaluation; rerun.",
            PACKAGED_GATE_HOLD,
        ]
    live_head = api.get(f"/branches/{quote(expected['head']['ref'], safe='')}")[
        "commit"
    ]["sha"]
    live_base = api.get("/branches/main")["commit"]["sha"]
    return admission_errors(
        expected, final, live_head, live_base, reviews, permissions, checks, issue
    )


def main() -> int:
    try:
        if os.environ["GITHUB_EVENT_NAME"] != "pull_request":
            raise ValueError("Only pull_request events are supported")
        event = json.loads(
            Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
        )
        expected = event["pull_request"]
        if expected["base"]["repo"]["full_name"] != os.environ["GITHUB_REPOSITORY"]:
            raise ValueError("Repository mismatch")
        errors = evaluate(
            GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"]), expected
        )
    except Exception:
        # Do not print request objects, headers, tokens, or user-controlled metadata.
        errors = [
            "Cannot verify complete current GitHub metadata; admission denied.",
            PACKAGED_GATE_HOLD,
        ]
    for error in errors:
        print(error, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
