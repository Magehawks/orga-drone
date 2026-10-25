"""Loopback Host and Origin checks (Issue #136)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.local_http import trusted_host, trusted_origin


def test_loopback_hosts_are_trusted() -> None:
    assert trusted_host("127.0.0.1:8765")
    assert trusted_host("localhost")
    assert trusted_host("[::1]:8765")
    assert trusted_host("testserver")
    assert not trusted_host("evil.example")
    assert not trusted_host("192.168.1.10:80")
    assert trusted_origin("http://127.0.0.1:8765", "localhost:8765")
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

    missing_origin = client.post("/studio/clear", headers={"Sec-Fetch-Site": "same-origin"})
    assert missing_origin.status_code in {200, 303, 404}
