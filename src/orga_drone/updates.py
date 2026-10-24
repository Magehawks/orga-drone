"""Optional notice for a newer published Windows release.

The lookup reads the public GitHub Release that ``/releases/latest`` already
exposes. Drafts, prereleases, and releases without the Windows zip do not
count. Nothing is downloaded or installed, and the request carries no library
or user data.

itch.io is not used: the Windows channel is still a draft/restricted butler
process and does not publish a comparable stable version.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from orga_drone import __version__

GITHUB_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/Magehawks/orga-drone/releases/latest"
)
OFFICIAL_DOWNLOAD_URL = "https://github.com/Magehawks/orga-drone/releases/latest"
WINDOWS_ZIP_NAME = "orga-drone-windows-x64.zip"
CHECK_TIMEOUT_S = 4.0
_USER_AGENT = "orga-drone"
_SEMVER = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_MAX_BODY = 1_000_000

FetchRelease = Callable[[], Any]


class UpdateLookupError(Exception):
    """The published release list could not be read."""


def installed_version() -> str:
    """Version baked into this build (``pyproject.toml`` via ``__version__``)."""
    return __version__


def parse_release_version(value: str) -> tuple[int, int, int] | None:
    """``X.Y.Z`` or ``vX.Y.Z``. Pre-release and build suffixes are rejected."""
    if not isinstance(value, str):
        return None
    match = _SEMVER.fullmatch(value.strip())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


@dataclass(frozen=True)
class UpdateReport:
    state: str
    current: str
    latest: str | None = None
    download_url: str = OFFICIAL_DOWNLOAD_URL

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "current": self.current,
            "latest": self.latest,
            "download_url": self.download_url,
        }


def _unavailable(current: str) -> UpdateReport:
    return UpdateReport(state="unavailable", current=current, latest=None)


def classify_github_release(payload: Any, *, current: str) -> UpdateReport:
    """Map one GitHub release document to update / current / unavailable."""
    installed = parse_release_version(current)
    if installed is None or not isinstance(payload, dict):
        return _unavailable(current)
    if payload.get("draft") is True or payload.get("prerelease") is True:
        return _unavailable(current)
    latest = parse_release_version(str(payload.get("tag_name") or ""))
    if latest is None:
        return _unavailable(current)
    assets = payload.get("assets")
    if not isinstance(assets, list):
        return _unavailable(current)
    names = {
        item.get("name")
        for item in assets
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    if WINDOWS_ZIP_NAME not in names:
        return _unavailable(current)
    latest_text = f"{latest[0]}.{latest[1]}.{latest[2]}"
    if latest > installed:
        return UpdateReport(state="update", current=current, latest=latest_text)
    return UpdateReport(state="current", current=current, latest=latest_text)


def fetch_latest_release(
    url: str = GITHUB_LATEST_RELEASE_URL,
    *,
    timeout: float = CHECK_TIMEOUT_S,
) -> Any:
    """GET the latest published release. No query string and no request body."""
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(_MAX_BODY + 1)
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise UpdateLookupError("release lookup failed") from exc
    if len(raw) > _MAX_BODY:
        raise UpdateLookupError("release lookup failed")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateLookupError("release lookup failed") from exc


class UpdateChecker:
    """One startup lookup per process; manual checks always ask again."""

    def __init__(self, fetch: FetchRelease | None = None) -> None:
        self._fetch = fetch or fetch_latest_release
        self._lock = threading.Lock()
        self._startup_result: UpdateReport | None = None

    def check(self, *, current: str, startup: bool) -> UpdateReport:
        if startup:
            with self._lock:
                if self._startup_result is not None:
                    return self._startup_result
                self._startup_result = self._lookup(current)
                return self._startup_result
        return self._lookup(current)

    def _lookup(self, current: str) -> UpdateReport:
        try:
            payload = self._fetch()
        except UpdateLookupError:
            return _unavailable(current)
        return classify_github_release(payload, current=current)
