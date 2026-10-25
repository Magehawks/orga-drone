"""Loopback Host and Origin checks (Issue #136)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from starlette.requests import Request

from orga_drone.config import Settings
from orga_drone.local_http import trusted_host, trusted_origin, write_is_allowed


def _request(headers: dict[str, str], *, scheme: str = "http") -> Request:
    encoded = [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in headers.items()]
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": scheme,
            "path": "/studio/clear",
            "raw_path": b"/studio/clear",
            "query_string": b"",
            "headers": encoded,
            "client": ("127.0.0.1", 9),
            "server": ("127.0.0.1", 8765),
        }
    )


def test_loopback_hosts_are_trusted() -> None:
    assert trusted_host("127.0.0.1:8765")
    assert trusted_host("localhost")
    assert trusted_host("[::1]:8765")
    assert trusted_host("testserver")
    assert not trusted_host("evil.example")
    assert not trusted_host("192.168.1.10:80")
    assert trusted_origin("http://127.0.0.1:8765", "127.0.0.1:8765")
    assert not trusted_origin("http://127.0.0.1:8765", "localhost:8765")
    assert not trusted_origin("http://127.0.0.1", "127.0.0.1:8765")
    assert not trusted_origin("https://127.0.0.1:8765", "127.0.0.1:8765", scheme="http")
    assert not trusted_origin("https://evil.example", "127.0.0.1:8765")


def test_foreign_host_and_origin_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    client = TestClient(create_app())
    local = client.get("/health")
    assert local.status_code == 200
    assert local.json()["status"] == "ok"

    foreign_host = client.get("/health", headers={"Host": "evil.example"})
    assert foreign_host.status_code == 403

    studio = client.get("/studio", headers={"Host": "attacker.local"})
    assert studio.status_code == 403

    cross = client.post(
        "/studio/clear",
        headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    )
    assert cross.status_code == 403

    same = client.post(
        "/studio/clear",
        headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
    )
    assert same.status_code in {200, 303, 404}


def test_write_without_origin_and_fetch_site_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    client = TestClient(create_app())
    missing = client.post(
        "/studio/clear",
        headers={"Origin": "", "Sec-Fetch-Site": "", "Referer": ""},
    )
    assert missing.status_code == 403

    site_only = client.post(
        "/studio/clear",
        headers={"Origin": "", "Sec-Fetch-Site": "same-origin", "Referer": ""},
    )
    assert site_only.status_code == 403

    wrong_port = client.post(
        "/studio/clear",
        headers={"Origin": "http://testserver:9", "Sec-Fetch-Site": "same-origin"},
    )
    assert wrong_port.status_code == 403

    https_origin = client.post(
        "/studio/clear",
        headers={"Origin": "https://testserver", "Sec-Fetch-Site": "same-origin"},
    )
    assert https_origin.status_code == 403

    assert write_is_allowed(
        _request({"host": "testserver", "origin": "", "sec-fetch-site": ""})
    ) is False
    assert write_is_allowed(
        _request({"host": "testserver", "sec-fetch-site": "same-origin"})
    ) is False


def test_desktop_write_with_matching_origin_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    client = TestClient(create_app())
    desktop = client.post(
        "/studio/clear",
        headers={
            "Host": "127.0.0.1:8765",
            "Origin": "http://127.0.0.1:8765",
            "Sec-Fetch-Site": "same-origin",
            "Referer": "http://127.0.0.1:8765/studio",
        },
    )
    assert desktop.status_code in {200, 303, 404}

    assert write_is_allowed(
        _request(
            {
                "host": "127.0.0.1:8765",
                "origin": "http://127.0.0.1:8765",
                "sec-fetch-site": "same-origin",
            }
        )
    )
    assert write_is_allowed(
        _request(
            {
                "host": "127.0.0.1:8765",
                "sec-fetch-site": "same-origin",
                "referer": "http://127.0.0.1:8765/studio",
            }
        )
    )
    assert write_is_allowed(
        _request(
            {
                "host": "127.0.0.1:8765",
                "sec-fetch-site": "same-origin",
                "referer": "http://localhost:8765/studio",
            }
        )
    ) is False
