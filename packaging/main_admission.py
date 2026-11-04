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
        for page in range(1, 11):
            data = self.get(f"{path}?per_page=100&page={page}")
            items = data[key] if key else data
            if not isinstance(items, list):
                raise ValueError("Invalid paginated metadata")
            result.extend(items)
            if len(items) < 100:
                return result
        raise ValueError("Incomplete metadata: pagination limit reached")


def evaluate(api: GitHub, expected: dict[str, Any]) -> list[str]:
    number = expected["number"]
    head, _ = candidate(expected)
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
    checks = api.pages(f"/commits/{head}/check-runs", "check_runs")
    runs = {}
    for check in checks:
        if check["name"] not in REQUIRED_CHECKS:
            continue
        match = re.fullmatch(
            re.escape(
                f"https://github.com/{expected['base']['repo']['full_name']}/actions/runs/"
            )
            + r"([0-9]+)/job/[0-9]+",
            check.get("details_url") or "",
        )
        if not match:
            raise ValueError("Cannot verify check workflow provenance")
        run_id = match[1]
        if run_id not in runs:
            runs[run_id] = api.get(f"/actions/runs/{run_id}")
        check["workflow"] = runs[run_id]
    issue_match = re.search(
        r"(?m)^Emergency issue: #([1-9][0-9]*)\s*$", current.get("body") or ""
    )
    issue = api.get(f"/issues/{issue_match[1]}") if issue_match else None
    # Re-read after collecting evidence, including real branch tips: PR base.sha
    # can lag the live branch. Any movement or metadata/API failure denies.
    final = api.get(f"/pulls/{number}")
    if current != final:
        return ["PR metadata changed during evaluation; rerun.", PACKAGED_GATE_HOLD]
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
