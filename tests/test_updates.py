"""Published Windows release notice: compare, opt-in, and failed lookups."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request

import pytest
from fastapi.testclient import TestClient

from orga_drone.app_prefs import get_check_updates, set_check_updates
from orga_drone.config import Settings
from orga_drone.updates import (
    GITHUB_LATEST_RELEASE_URL,
    OFFICIAL_DOWNLOAD_URL,
    UpdateChecker,
    UpdateLookupError,
    classify_github_release,
    fetch_latest_release,
    parse_release_version,
)


def _release(
    tag: str,
    *,
    draft: bool = False,
    prerelease: bool = False,
    asset: str | None = "orga-drone-windows-x64.zip",
) -> dict:
    assets = [] if asset is None else [{"name": asset}]
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "assets": assets,
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.9.0", (1, 9, 0)),
        ("v1.10.0", (1, 10, 0)),
        ("1.9.0-rc1", None),
        ("v1.9.0-beta", None),
        ("1.9", None),
        ("dev", None),
    ],
)
def test_parse_release_version(
    value: str, expected: tuple[int, int, int] | None
) -> None:
    assert parse_release_version(value) == expected


def test_newer_stable_windows_release_is_an_update() -> None:
    report = classify_github_release(_release("v1.10.0"), current="1.9.0")
    assert report.state == "update"
    assert report.latest == "1.10.0"
    assert report.download_url == OFFICIAL_DOWNLOAD_URL


def test_same_or_older_release_is_current() -> None:
    assert (
        classify_github_release(_release("v1.9.0"), current="1.9.0").state == "current"
    )
    assert (
        classify_github_release(_release("v1.8.0"), current="1.9.0").state == "current"
    )


@pytest.mark.parametrize(
    "payload",
    [
        _release("v1.10.0", draft=True),
        _release("v1.10.0", prerelease=True),
        _release("v1.10.0-rc1"),
        _release("v1.10.0", asset=None),
        _release("v1.10.0", asset="source.tar.gz"),
        {"tag_name": "v1.10.0"},
        None,
        "nope",
    ],
)
def test_untrustworthy_release_does_not_notify(payload: object) -> None:
    assert classify_github_release(payload, current="1.9.0").state == "unavailable"


def test_lookup_failure_is_unavailable() -> None:
    def boom() -> dict:
        raise UpdateLookupError("offline")

    report = UpdateChecker(boom).check(current="1.9.0", startup=False)
    assert report.state == "unavailable"


def test_startup_check_runs_once() -> None:
    calls = {"n": 0}

    def fetch() -> dict:
        calls["n"] += 1
        return _release("v1.10.0")

    checker = UpdateChecker(fetch)
    first = checker.check(current="1.9.0", startup=True)
    second = checker.check(current="1.9.0", startup=True)
    assert first.state == "update"
    assert second.state == "update"
    assert calls["n"] == 1
    checker.check(current="1.9.0", startup=False)
    assert calls["n"] == 2


def test_fetch_sends_no_query_or_body(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Request] = {}

    class _Response:
        def read(self, _limit: int) -> bytes:
            return b'{"tag_name":"v1.9.0","draft":false,"prerelease":false,"assets":[]}'

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_urlopen(request: Request, timeout: float = 0) -> _Response:
        captured["request"] = request
        captured["timeout"] = timeout  # type: ignore[assignment]
        return _Response()

    monkeypatch.setattr("orga_drone.updates.urllib.request.urlopen", fake_urlopen)
    fetch_latest_release()
    request = captured["request"]
    assert captured["timeout"] == 4.0
    assert request.full_url == GITHUB_LATEST_RELEASE_URL
    assert "?" not in request.full_url
    assert request.data is None
    assert request.get_method() == "GET"
    assert request.get_header("User-agent") == "orga-drone"


def test_fetch_timeout_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Request, timeout: float = 0) -> object:
        raise TimeoutError("slow")

    monkeypatch.setattr("orga_drone.updates.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(UpdateLookupError):
        fetch_latest_release()


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    monkeypatch.setattr(
        "orga_drone.app_prefs.settings", Settings(data_dir=tmp_path / "data")
    )
    from orga_drone.app import create_app

    return TestClient(create_app())


def test_check_updates_defaults_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.app_prefs.settings", Settings(data_dir=tmp_path / "data")
    )
    assert get_check_updates() is False
    client = _client(tmp_path, monkeypatch)
    html = client.get("/").text
    assert 'data-update-check="0"' in html
    assert 'id="about-check-updates"' in html
    assert (
        "checked" not in html.split('id="about-check-updates"', 1)[1].split(">", 1)[0]
    )

    def fail_fetch() -> dict:
        raise AssertionError("disabled startup must not look up a release")

    client.app.state.update_checker = UpdateChecker(fail_fetch)
    skipped = client.post("/api/updates/check", json={"startup": True})
    assert skipped.status_code == 200
    assert skipped.json()["state"] == "skipped"
    assert skipped.json()["checked"] is False


def test_opt_in_persists_and_startup_checks_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    saved = client.post("/api/updates/preference", json={"enabled": True})
    assert saved.json()["enabled"] is True
    assert get_check_updates() is True
    html = client.get("/").text
    assert 'data-update-check="1"' in html
    calls = {"n": 0}

    def fetch() -> dict:
        calls["n"] += 1
        return _release("v9.0.0")

    client.app.state.update_checker = UpdateChecker(fetch)
    first = client.post("/api/updates/check", json={"startup": True}).json()
    second = client.post("/api/updates/check", json={"startup": True}).json()
    assert first["state"] == "update"
    assert first["latest"] == "9.0.0"
    assert second["state"] == "update"
    assert calls["n"] == 1
    client.post("/api/updates/preference", json={"enabled": False})
    assert get_check_updates() is False


def test_manual_check_reports_current_and_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)

    def current() -> dict:
        return _release("v1.9.0")

    client.app.state.update_checker = UpdateChecker(current)
    body = client.post("/api/updates/check", json={"startup": False}).json()
    assert body["state"] == "current"
    assert body["checked"] is True

    def offline() -> dict:
        raise UpdateLookupError("offline")

    client.app.state.update_checker = UpdateChecker(offline)
    failed = client.post("/api/updates/check", json={}).json()
    assert failed["state"] == "unavailable"


def test_open_download_ignores_client_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    response = client.post(
        "/api/updates/open-download",
        json={"url": "https://example.invalid/evil"},
    )
    assert response.status_code == 200
    assert opened == [OFFICIAL_DOWNLOAD_URL]
    assert response.json()["url"] == OFFICIAL_DOWNLOAD_URL


def test_about_shows_installed_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orga_drone import __version__

    client = _client(tmp_path, monkeypatch)
    html = client.get("/").text
    assert "About Orga Drone" in html or "Über Orga Drone" in html
    assert f">v{__version__}</span>" in html
    assert OFFICIAL_DOWNLOAD_URL in html
    script = Path("src/orga_drone/static/js/updates.js").read_text(encoding="utf-8")
    assert 'dataset.updateCheck === "1"' in script
    assert "sessionStorage" in script


def test_preference_rejects_non_bool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    response = client.post(
        "/api/updates/preference",
        content=json.dumps({"enabled": "yes"}),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    set_check_updates(True)
    assert get_check_updates() is True
