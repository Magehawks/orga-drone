"""Read-only main admission guard for develop/hotfix promotions to main.

Only GitHub metadata and the small packaged-E2E evidence artifact are read. No
PR code, labels, or supplied results can enable admission. The workflow executes
this file from its base SHA.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

_PACKAGING_DIR = str(Path(__file__).resolve().parent)
if _PACKAGING_DIR not in sys.path:
    sys.path.insert(0, _PACKAGING_DIR)
import packaged_e2e  # type: ignore[import-not-found]  # noqa: E402

REQUIRED_CHECKS = (
    "Ruff, MyPy and unit tests",
    "JavaScript lint, format and tests",
    "App journey smoke",
)
CI_WORKFLOW_FILE = "ci.yml"
CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
E2E_WORKFLOW_FILE = "windows-e2e.yml"
E2E_WORKFLOW_PATH = ".github/workflows/windows-e2e.yml"
PACKAGED_E2E_CHECK = "Windows packaged E2E"
E2E_TRUSTED_PATHS = (
    E2E_WORKFLOW_PATH,
    "packaging/e2e/windows_e2e.py",
    "packaging/packaged_e2e.py",
)
OWNER_AUTHORIZATION_ENABLED = True
OWNER_AUTH_PREFIX = "Main admission owner authorization:"
OWNER_ARTIFACT_PREFIX = "Main admission artifact:"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def candidate(pr: dict[str, Any]) -> tuple[str, str]:
    return pr["head"]["sha"], pr["base"]["sha"]


def _timestamp_at_or_after(value: Any, reference: Any) -> bool:
    if not isinstance(value, str) or not isinstance(reference, str):
        return False
    try:
        current = datetime.fromisoformat(value.replace("Z", "+00:00"))
        after = datetime.fromisoformat(reference.replace("Z", "+00:00"))
    except ValueError:
        return False
    return current >= after


def owner_authorization_ok(
    comments: list[dict[str, Any]],
    *,
    head: str,
    base: str,
    evidence: dict[str, Any] | None,
    permissions: dict[str, str],
) -> bool:
    """Accept an explicit admin-owner comment bound to the exact candidate."""
    if not OWNER_AUTHORIZATION_ENABLED or evidence is None:
        return False
    digest = packaged_e2e.sha256_hex(str(evidence.get("artifact_sha256") or ""))
    if not _SHA256_RE.fullmatch(digest):
        return False
    marker = f"{OWNER_AUTH_PREFIX} {head} {base}"
    artifact_marker = f"{OWNER_ARTIFACT_PREFIX} sha256:{digest}"
    for comment in comments:
        user = comment.get("user") or {}
        login = user.get("login")
        if not isinstance(login, str) or user.get("type") != "User":
            continue
        if permissions.get(login) != "admin":
            continue
        body = comment.get("body") or ""
        if not isinstance(body, str):
            continue
        lines = body.splitlines()
        if marker not in lines or artifact_marker not in lines:
            continue
        if not _timestamp_at_or_after(
            comment.get("created_at"), evidence.get("generated_at")
        ):
            continue
        return True
    return False


def admission_errors(
    expected: dict[str, Any],
    current: dict[str, Any],
    live_head: str,
    live_base: str,
    reviews: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    permissions: dict[str, str],
    checks: list[dict[str, Any]],
    emergency_issue: dict[str, Any] | None,
    packaged_e2e: dict[str, Any] | None,
    packaged_e2e_errors: list[str],
) -> list[str]:
    """Diagnose necessary conditions. An empty list means admission may pass."""
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

    # Comments do not revoke a review; a later decisive review does.
    latest: dict[str, dict[str, Any]] = {}
    for review in sorted(reviews, key=lambda item: item["id"]):
        if review["state"] in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            latest[review["user"]["login"]] = review
    marker = f"Main admission candidate: {head} {base}"
    review_ok = any(
        review["state"] == "APPROVED"
        and review["commit_id"] == head
        and review["user"]["type"] == "User"
        and login != current["user"]["login"]
        and permissions.get(login) in {"write", "maintain", "admin"}
        and marker in (review.get("body") or "").splitlines()
        for login, review in latest.items()
    )
    owner_ok = owner_authorization_ok(
        comments, head=head, base=base, evidence=packaged_e2e, permissions=permissions
    )
    if not (review_ok or owner_ok):
        errors.append(
            "Missing independent human approval or explicit owner authorization for this exact head/base."
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
            and check["workflow"]["path"] == CI_WORKFLOW_PATH
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

    errors.extend(packaged_e2e_errors)
    return errors


class _StripAuthOnCrossHostRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward the GitHub token to the signed artifact storage host."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        if urlsplit(newurl).scheme != "https":
            return None
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and urlsplit(newurl).netloc != urlsplit(
            req.full_url
        ).netloc:
            redirected.remove_header("Authorization")
        return redirected


class GitHub:
    def __init__(self, repo: str, token: str):
        if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) is None:
            raise ValueError("Invalid repository")
        self.root = f"https://api.github.com/repos/{repo}"
        self.token = token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def get(self, path: str) -> Any:
        request = urllib.request.Request(self.root + path, headers=self._headers())
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    def permission(self, login: str) -> str:
        """Return a collaborator permission; a non-collaborator is ``none``."""
        try:
            return str(
                self.get(f"/collaborators/{quote(login, safe='')}/permission")[
                    "permission"
                ]
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return "none"
            raise

    def download(self, path: str, *, max_bytes: int) -> bytes:
        request = urllib.request.Request(self.root + path, headers=self._headers())
        opener = urllib.request.build_opener(_StripAuthOnCrossHostRedirect())
        chunks = []
        total = 0
        with opener.open(request, timeout=30) as response:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("Downloaded evidence artifact is too large")
                chunks.append(chunk)
        return b"".join(chunks)

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


def newest_workflow_run(
    api: GitHub, pr: dict[str, Any], workflow_file: str
) -> dict[str, Any]:
    head = pr["head"]["sha"]
    runs = api.pages(
        f"/actions/workflows/{workflow_file}/runs?event=pull_request&head_sha={head}",
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
        raise ValueError("Missing PR workflow run")
    return max(matching, key=lambda run: run["id"])


def validated_run(
    api: GitHub,
    pr: dict[str, Any],
    selected: dict[str, Any],
    workflow_path: str,
) -> dict[str, Any]:
    run = api.get(f"/actions/runs/{selected['id']}")
    repo = pr["base"]["repo"]["full_name"]
    if (
        run["id"] != selected["id"]
        or run["path"] != workflow_path
        or run["event"] != "pull_request"
        or run["head_sha"] != pr["head"]["sha"]
        or run["repository"]["full_name"] != repo
        or not linked_candidate(run, pr)
        or not isinstance(run["run_attempt"], int)
        or run["run_attempt"] < 1
    ):
        raise ValueError("Unverified workflow run/candidate")
    return run


def job_check(
    api: GitHub,
    run: dict[str, Any],
    job: dict[str, Any],
    repo: str,
    pr: dict[str, Any],
) -> dict[str, Any]:
    prefix = f"{api.root}/check-runs/"
    if not job["check_run_url"].startswith(prefix):
        raise ValueError("Untrusted check URL")
    check_id = job["check_run_url"][len(prefix) :]
    if not re.fullmatch(r"[0-9]+", check_id):
        raise ValueError("Invalid check ID")
    check = api.get(f"/check-runs/{check_id}")
    if (
        job["run_id"] != run["id"]
        or job["run_attempt"] != run["run_attempt"]
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
    return check


def collect_workflow_checks(
    api: GitHub,
    pr: dict[str, Any],
    *,
    workflow_file: str,
    workflow_path: str,
    required_names: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Use one explicit workflow run/attempt, never commit-wide filter=latest."""
    selected = newest_workflow_run(api, pr, workflow_file)
    run = validated_run(api, pr, selected, workflow_path)
    attempt = run["run_attempt"]
    jobs = api.pages(f"/actions/runs/{run['id']}/attempts/{attempt}/jobs", "jobs")
    checks = []
    for job in jobs:
        if job["name"] not in required_names:
            continue
        checks.append(job_check(api, run, job, pr["base"]["repo"]["full_name"], pr))
    # A partial rerun cannot borrow successes from an earlier attempt. Also
    # reject a run/attempt or newest-run change while collecting its evidence.
    if (
        api.get(f"/actions/runs/{run['id']}") != run
        or newest_workflow_run(api, pr, workflow_file)["id"] != run["id"]
    ):
        raise ValueError("Workflow run/attempt changed during collection")
    return checks


def collect_checks(api: GitHub, pr: dict[str, Any]) -> list[dict[str, Any]]:
    return collect_workflow_checks(
        api,
        pr,
        workflow_file=CI_WORKFLOW_FILE,
        workflow_path=CI_WORKFLOW_PATH,
        required_names=REQUIRED_CHECKS,
    )


def trusted_file_sha(api: GitHub, path: str, ref: str) -> str:
    data = api.get(f"/contents/{quote(path, safe='/')}?ref={quote(ref, safe='')}")
    if not isinstance(data, dict) or data.get("type") != "file":
        raise ValueError(f"Trusted E2E file is missing: {path}")
    sha = data.get("sha")
    if not isinstance(sha, str):
        raise ValueError(f"Trusted E2E file has no blob SHA: {path}")
    return sha


def _find_artifact(artifacts: list[dict[str, Any]], name: str) -> dict[str, Any]:
    matching = [item for item in artifacts if item.get("name") == name]
    if len(matching) != 1:
        raise ValueError(f"Missing or ambiguous artifact: {name}")
    return matching[0]


def _artifact_identity(
    artifact: dict[str, Any], run: dict[str, Any], head: str
) -> None:
    workflow_run = artifact.get("workflow_run")
    if not isinstance(workflow_run, dict) or workflow_run.get("id") != run["id"]:
        raise ValueError("Artifact is not from this workflow run")
    if workflow_run.get("head_sha") != head:
        raise ValueError("Artifact head SHA mismatch")
    if artifact.get("expired") is not False:
        raise ValueError("Artifact is expired or has no expiry state")
    digest = artifact.get("digest")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(
        packaged_e2e.sha256_hex(digest)
    ):
        raise ValueError("Artifact digest is missing or invalid")


def collect_packaged_e2e(
    api: GitHub, pr: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    """Verify the packaged Windows E2E run, artifacts, and evidence binding."""
    try:
        selected = newest_workflow_run(api, pr, E2E_WORKFLOW_FILE)
        run = validated_run(api, pr, selected, E2E_WORKFLOW_PATH)
        attempt = run["run_attempt"]
        head = pr["head"]["sha"]
        repo = pr["base"]["repo"]["full_name"]
        jobs = api.pages(f"/actions/runs/{run['id']}/attempts/{attempt}/jobs", "jobs")
        matching = [job for job in jobs if job["name"] == PACKAGED_E2E_CHECK]
        if len(matching) != 1:
            raise ValueError("Missing or ambiguous packaged E2E job")
        check = job_check(api, run, matching[0], repo, pr)
        if check["status"] != "completed" or check["conclusion"] != "success":
            raise ValueError("Packaged E2E check was not successful")

        app_name, evidence_name = packaged_e2e.artifact_names(attempt, head)
        artifacts = api.pages(f"/actions/runs/{run['id']}/artifacts", "artifacts")
        app_artifact = _find_artifact(artifacts, app_name)
        evidence_artifact = _find_artifact(artifacts, evidence_name)
        _artifact_identity(app_artifact, run, head)
        _artifact_identity(evidence_artifact, run, head)

        payload = api.download(
            f"/actions/artifacts/{evidence_artifact['id']}/zip",
            max_bytes=packaged_e2e.MAX_EVIDENCE_ZIP_BYTES,
        )
        evidence_digest = hashlib.sha256(payload).hexdigest()
        if evidence_digest != packaged_e2e.sha256_hex(str(evidence_artifact["digest"])):
            raise ValueError("Evidence artifact digest mismatch")
        evidence = packaged_e2e.parse_evidence_zip(payload)

        merge_sha = pr.get("merge_commit_sha")
        if not isinstance(merge_sha, str) or not re.fullmatch(
            r"[0-9a-f]{40}", merge_sha
        ):
            raise ValueError("PR merge commit is unavailable")
        commit = api.get(f"/git/commits/{merge_sha}")
        tree = (commit.get("tree") or {}).get("sha")
        if commit.get("sha") != merge_sha or not isinstance(tree, str):
            raise ValueError("PR merge tree cannot be verified")

        errors = packaged_e2e.evidence_errors(
            evidence,
            repository=repo,
            pr_number=pr["number"],
            head_sha=head,
            base_sha=pr["base"]["sha"],
            merge_sha=merge_sha,
            tree_sha=tree,
            run_id=run["id"],
            run_attempt=attempt,
            app_artifact_name=app_name,
        )
        if errors:
            return None, errors

        for path in E2E_TRUSTED_PATHS:
            if trusted_file_sha(api, path, head) != trusted_file_sha(
                api, path, pr["base"]["sha"]
            ):
                return None, [f"Packaged E2E trusted file changed: {path}"]

        if (
            api.get(f"/actions/runs/{run['id']}") != run
            or newest_workflow_run(api, pr, E2E_WORKFLOW_FILE)["id"] != run["id"]
        ):
            raise ValueError("Packaged E2E run changed during collection")
        rechecked = api.pages(f"/actions/runs/{run['id']}/artifacts", "artifacts")
        for artifact in (app_artifact, evidence_artifact):
            try:
                current = _find_artifact(rechecked, artifact["name"])
            except ValueError as exc:
                raise ValueError("Packaged E2E artifact changed") from exc
            if current.get("id") != artifact.get("id") or current.get(
                "digest"
            ) != artifact.get("digest"):
                raise ValueError("Packaged E2E artifact changed during collection")
        return evidence, []
    except (ValueError, KeyError, TypeError) as exc:
        return None, [f"Packaged Windows E2E evidence unavailable: {exc}"]


def evaluate(api: GitHub, expected: dict[str, Any]) -> list[str]:
    number = expected["number"]
    current = api.get(f"/pulls/{number}")
    reviews = api.pages(f"/pulls/{number}/reviews")
    comments = api.pages(f"/issues/{number}/comments")
    logins = {
        r["user"]["login"]
        for r in reviews
        if r["state"] == "APPROVED" and r["user"]["type"] == "User"
    }
    logins.update(
        c["user"]["login"]
        for c in comments
        if isinstance(c.get("body"), str)
        and OWNER_AUTH_PREFIX in c["body"]
        and isinstance(c.get("user"), dict)
        and isinstance(c["user"].get("login"), str)
    )
    permissions = {login: api.permission(login) for login in logins}
    checks = collect_checks(api, expected)
    packaged_e2e, packaged_e2e_errors = collect_packaged_e2e(api, current)
    issue_match = re.search(
        r"(?m)^Emergency issue: #([1-9][0-9]*)\s*$", current.get("body") or ""
    )
    issue = api.get(f"/issues/{issue_match[1]}") if issue_match else None
    # Re-read after collecting evidence, including real branch tips: PR base.sha
    # can lag the live branch. Any movement or metadata/API failure denies.
    final = api.get(f"/pulls/{number}")
    if (
        current != final
        or api.pages(f"/pulls/{number}/reviews") != reviews
        or api.pages(f"/issues/{number}/comments") != comments
    ):
        return ["PR/review/comment metadata changed during evaluation; rerun."]
    live_head = api.get(f"/branches/{quote(expected['head']['ref'], safe='')}")[
        "commit"
    ]["sha"]
    live_base = api.get("/branches/main")["commit"]["sha"]
    return admission_errors(
        expected,
        final,
        live_head,
        live_base,
        reviews,
        comments,
        permissions,
        checks,
        issue,
        packaged_e2e,
        packaged_e2e_errors,
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
        errors = ["Cannot verify complete current GitHub metadata; admission denied."]
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
