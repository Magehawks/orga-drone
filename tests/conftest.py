"""Pytest session isolation (issue-review requirement for #388).

This block runs BEFORE any ``orga_drone`` import: the whole test session
uses a temporary app-data directory by default. Module-level ``settings``
bindings (``thumbs.py`` and friends bind ``settings`` at import time) all
resolve inside this session directory, so a forgotten test-level patch
cannot write real user data. Individual tests still patch
``Settings``/module bindings with their own ``tmp_path`` â€” that stays the
required pattern for anything touching app state.
"""

from __future__ import annotations

import os
import tempfile

_SESSION_APP_DATA = tempfile.mkdtemp(prefix="orga-drone-pytest-appdata-")
os.environ["ORGA_DRONE_DATA_DIR"] = _SESSION_APP_DATA

# Imports stay below the session override on purpose (E402): every
# orga_drone module must see the temporary app-data directory at import
# time, including module-level settings bindings.
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from starlette.testclient import TestClient as StarletteTestClient  # noqa: E402

from tests.appdata_guard import (  # noqa: E402
    assert_untouched,
    real_default_data_dir,
    sqlite_snapshot,
)

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
    """Backstop: fail any test that writes the platform-default database.

    The session-level ``ORGA_DRONE_DATA_DIR`` (top of this file) already
    redirects every settings binding into a temporary directory. This
    fixture additionally watches the PLATFORM-default location (resolved
    with the override removed): if that database is created, modified, or
    deleted during a test, the test fails with an actionable message. That
    covers paths that bypass ``settings`` entirely. Rebuildable caches
    (thumbs etc.) are redirected by the same session override; the
    platform-default watch is limited to the user database and its WAL/SHM
    sidecars.
    """
    data_dir = real_default_data_dir()
    before = sqlite_snapshot(data_dir)
    yield
    assert_untouched(before, data_dir)
