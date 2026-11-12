"""Pytest session isolation (issue-review requirement for #388).

The whole test session uses a temporary app-data directory by default:

1. ``ORGA_DRONE_DATA_DIR`` is set BEFORE any ``orga_drone`` import.
2. The global ``settings`` singleton is REPLACED with an equivalent
   instance pointing into the same session directory, and every module
   that bound ``settings`` at import time is re-pointed too (module-level
   ``from orga_drone.config import settings`` bindings would otherwise
   keep the instance created during their import).

A forgotten test-level patch therefore cannot write real user data.
Individual tests still patch ``Settings``/module bindings with their own
``tmp_path`` — that stays the required pattern for anything touching app
state.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_SESSION_APP_DATA = Path(tempfile.mkdtemp(prefix="orga-drone-pytest-appdata-"))
os.environ["ORGA_DRONE_DATA_DIR"] = str(_SESSION_APP_DATA)

# Imports stay below the session override on purpose (E402): every
# orga_drone module must see the temporary app-data directory at import
# time, including module-level settings bindings.
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from starlette.testclient import TestClient as StarletteTestClient  # noqa: E402

import orga_drone.app  # noqa: E402
import orga_drone.app_prefs  # noqa: E402
import orga_drone.auto_tags  # noqa: E402
import orga_drone.desktop  # noqa: E402
import orga_drone.studio_export  # noqa: E402
import orga_drone.thumbs  # noqa: E402
import orga_drone.config as _orga_config  # noqa: E402
from orga_drone.config import Settings  # noqa: E402

from tests.appdata_guard import (  # noqa: E402
    assert_untouched,
    real_default_data_dir,
    sqlite_snapshot,
)

#: The global singleton was created during the imports above — under the
#: session override it already resolves into the session directory. Re-point
#: every module binding at THAT instance (a single object everywhere).
_SESSION_SETTINGS = _orga_config.settings
if Path(_SESSION_SETTINGS.data_dir) != _SESSION_APP_DATA:
    _SESSION_SETTINGS = Settings(data_dir=_SESSION_APP_DATA)
    _orga_config.settings = _SESSION_SETTINGS

#: Modules that bind ``settings`` at import time. The list is asserted
#: complete by tests/test_test_isolation.py against a grep of the source.
_SETTINGS_BINDING_MODULES = (
    orga_drone.app,
    orga_drone.app_prefs,
    orga_drone.auto_tags,
    orga_drone.desktop,
    orga_drone.studio_export,
    orga_drone.thumbs,
)

for _module in _SETTINGS_BINDING_MODULES:
    _module.settings = _SESSION_SETTINGS

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

    The session-level override above already redirects every known
    settings binding into a temporary directory. This fixture additionally
    watches the PLATFORM-default location (resolved with the override
    removed): if that database or its WAL/SHM sidecars are created,
    modified, or deleted during a test, the test fails with an actionable
    message. That covers paths that bypass ``settings`` entirely.
    Rebuildable caches (thumbs etc.) are redirected by the same session
    override; the platform-default watch is limited to the user database
    and its sidecars.
    """
    data_dir = real_default_data_dir()
    before = sqlite_snapshot(data_dir)
    yield
    assert_untouched(before, data_dir)
