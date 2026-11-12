"""Guard helpers that keep tests and debug scripts out of real app data.

A handful of past incidents had temporary debug scripts run against the
production AppData database (they forgot to patch ``settings``). These
helpers snapshot the real SQLite database around every test (via the
autouse fixture in ``tests/conftest.py``) and fail loudly when a test
created, modified, or deleted it. Thumbs and other rebuildable caches are
out of scope here (they are owned, rebuildable caches); the user database
is the critical artifact.

The real directory is resolved through ``_default_data_dir`` with any
``ORGA_DRONE_DATA_DIR`` override removed, so the guard watches the same
location a leaked write would hit.
"""

from __future__ import annotations

import os
from pathlib import Path

DB_FILENAME = "orga-drone.sqlite3"


def real_default_data_dir() -> Path:
    """The platform-default app data directory, ignoring ORGA_DRONE_DATA_DIR."""
    saved = os.environ.pop("ORGA_DRONE_DATA_DIR", None)
    try:
        from orga_drone.config import _default_data_dir

        return _default_data_dir()
    finally:
        if saved is not None:
            os.environ["ORGA_DRONE_DATA_DIR"] = saved


def sqlite_snapshot(data_dir: Path) -> int | None:
    """Modification timestamp of the real database file, or None when absent."""
    path = data_dir / DB_FILENAME
    return path.stat().st_mtime_ns if path.exists() else None


def assert_untouched(before: int | None, data_dir: Path) -> None:
    """Fail when the database file was created, modified, or deleted."""
    path = data_dir / DB_FILENAME
    after = path.stat().st_mtime_ns if path.exists() else None
    if before is None and after is not None:
        raise AssertionError(
            f"A test created the real app-data database: {path}. Tests must "
            "patch Settings with a temporary data_dir."
        )
    if before is not None and after is None:
        raise AssertionError(f"A test deleted the real app-data database: {path}")
    if before is not None and after is not None and after != before:
        raise AssertionError(
            f"A test wrote the real app-data database: {path}. Tests must "
            "patch Settings with a temporary data_dir."
        )
