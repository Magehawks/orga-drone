"""Application version in UI and health endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone import __version__
from orga_drone.app import PACKAGE_DIR
from orga_drone.config import Settings


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    return TestClient(create_app())


def test_health_returns_package_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.get("/health").json() == {"status": "ok", "version": __version__}


def test_dashboard_footer_shows_package_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    html = client.get("/").text
    assert f'<span class="app-version">v{__version__}</span>' in html


def test_studio_topbar_shows_package_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    html = client.get("/studio").text
    assert '<span class="app-version studio-app-version"' in html
    assert f">v{__version__}</span>" in html


def test_base_template_references_version_context() -> None:
    html = (PACKAGE_DIR / "templates" / "base.html").read_text(encoding="utf-8")
    assert 'class="app-version">v{{ version }}</span>' in html
