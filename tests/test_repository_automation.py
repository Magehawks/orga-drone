"""Guard repository automation against accidental releases and notifications.

These checks are intentionally text-based so they do not add a YAML dependency.
They verify the policy in docs/RELEASE_SECURITY.md.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
WINDOWS_BUILD = WORKFLOWS / "windows-release.yml"
CI = WORKFLOWS / "ci.yml"

FORBIDDEN_AUTOMATION = (
    "DISCORD_RELEASE_WEBHOOK",
    "discord.com/api/webhooks",
    "gh release",
    "repository_dispatch",
    "workflow_run",
    "butler",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _trigger_keys(text: str) -> list[str]:
    match = re.search(
        r"(?m)^on:[ \t]*\n(?P<body>(?:(?:[ \t]+[^\n]*)?\n)*)",
        text,
    )
    assert match is not None, "workflow has no top-level on: block"
    keys: list[str] = []
    for line in match.group("body").splitlines():
        key = re.match(r"^  ([A-Za-z_]+):(?:\s|$)", line)
        if key:
            keys.append(key.group(1))
    return keys


def test_cursor_configuration_is_local_only() -> None:
    gitignore = _read(ROOT / ".gitignore")
    lines = [line.strip() for line in gitignore.splitlines()]
    assert ".cursor/" in lines
    assert not any(line.startswith("!.cursor") for line in lines)


def test_windows_build_is_manual_only() -> None:
    text = _read(WINDOWS_BUILD)
    assert _trigger_keys(text) == ["workflow_dispatch"]
    assert "contents: write" not in text
    assert not any(entry in text for entry in FORBIDDEN_AUTOMATION)


def test_ci_keeps_the_required_checks() -> None:
    text = _read(CI)
    assert set(_trigger_keys(text)) == {
        "pull_request",
        "workflow_dispatch",
        "workflow_call",
    }
    for command in (
        "ruff check .",
        "mypy src packaging/itch_channel.py packaging/windows_third_party.py",
        "pytest --ignore=tests/test_pr_journey_smoke.py",
        "npm run lint:js",
        "npm run format:check",
        "npm run test:js",
        "pytest tests/test_pr_journey_smoke.py",
    ):
        assert command in text


def test_no_automatic_release_or_notification_workflow() -> None:
    assert not (WORKFLOWS / "itch-test-channel-notice.yml").exists()
    allowed_triggers = {"pull_request", "workflow_dispatch", "workflow_call"}
    for path in WORKFLOWS.glob("*.yml"):
        text = _read(path)
        assert set(_trigger_keys(text)) <= allowed_triggers, path.name
        assert not any(entry in text for entry in FORBIDDEN_AUTOMATION), path.name
