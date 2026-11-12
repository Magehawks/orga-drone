"""Default TestClient Origin matches Starlette's http://testserver Host."""

from __future__ import annotations

from typing import Any

import pytest
from starlette.testclient import TestClient as StarletteTestClient

from tests.appdata_guard import assert_untouched, real_default_data_dir, sqlite_snapshot

_DEFAULT_HEADERS = {
    "Origin": "http://testserver",
    "Sec-Fetch-Site": "same-origin",
}


@pytest.fixture(autouse=True)
def _default_loopback_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    original = StarletteTestClient.__init__

    def _init(self: StarletteTestClient, *args: Any, **kwargs: Any) -> None:
        headers = dict(kwargs.get("headers") or {})
        for key, value in _DEFAULT_HEADERS.items():
            headers.setdefault(key, value)
        kwargs["headers"] = headers
        original(self, *args, **kwargs)

    monkeypatch.setattr(StarletteTestClient, "__init__", _init)


@pytest.fixture(autouse=True)
def _protect_real_app_data() -> None:
    """Fail any test that writes the real app-data SQLite database.

    Past incidents had debug scripts and under-patched tests run against
    the production database. Every test is wrapped: the database is
    snapshotted before and compared after. Tests must patch Settings with
    a temporary data_dir (see tests/appdata_guard.py).
    """
    data_dir = real_default_data_dir()
    before = sqlite_snapshot(data_dir)
    yield
    assert_untouched(before, data_dir)
