"""Default TestClient Origin matches Starlette's http://testserver Host."""

from __future__ import annotations

from typing import Any

import pytest
from starlette.testclient import TestClient as StarletteTestClient

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
