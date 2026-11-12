"""Guard helpers that keep tests and debug scripts out of real app data.

Two layers of protection:

1. **Preventive (conftest.py, top of file):** the entire pytest session
   runs with ``ORGA_DRONE_DATA_DIR`` pointed at a temporary directory set
   BEFORE any ``orga_drone`` import. Module-level ``settings`` bindings
   (``thumbs.py`` and friends bind ``settings`` at import time) therefore
   resolve inside the session directory even when a test forgets its own
   patch. Individual tests still patch ``Settings``/module bindings with
   their own ``tmp_path`` — that stays the required pattern for anything
   touching app state.
2. **Detective (``_protect_real_app_data`` fixture):** the platform-default
   location — resolved with the override removed — is watched around every
   test. If the real database or its WAL/SHM sidecars are created,
   modified, or deleted during a test, the test fails with an actionable
   message. This catches paths that bypass ``settings`` entirely.

Standalone debug scripts MUST set ``ORGA_DRONE_DATA_DIR`` inside their own
process before importing ``orga_drone`` — pytest-level protection does not
apply to them.

## Documented limits

- This is Python/pytest-level isolation, **not** OS-level sandboxing: code
  that computes the AppData path independently and writes there without
  using ``orga_drone.config`` would not be redirected (though the
  detective fixture would still flag it afterwards).
- The detective check runs at test boundaries; a write performed by a
  still-running background thread could land after the check. Daemon
  threads are stopped by process exit; tests that spawn workers should
  join them.
- Rebuildable caches are redirected by the session override; the
  platform-default watch covers only the database and its WAL/SHM
  sidecars.
"""

from __future__ import annotations

import os
from pathlib import Path

DB_FILENAME = "orga-drone.sqlite3"
DB_SIDECARS = ("-wal", "-shm")


def real_default_data_dir() -> Path:
    """The platform-default app data directory, ignoring ORGA_DRONE_DATA_DIR."""
    saved = os.environ.pop("ORGA_DRONE_DATA_DIR", None)
    try:
        from orga_drone.config import _default_data_dir

        return _default_data_dir()
    finally:
        if saved is not None:
            os.environ["ORGA_DRONE_DATA_DIR"] = saved


def _watched_files(data_dir: Path) -> tuple[Path, ...]:
    base = data_dir / DB_FILENAME
    return (base, *(base.with_name(base.name + suffix) for suffix in DB_SIDECARS))


def sqlite_snapshot(data_dir: Path) -> dict[Path, int | None]:
    """Modification timestamps of the real database and its WAL/SHM sidecars
    (None when a file is absent)."""
    return {path: (path.stat().st_mtime_ns if path.exists() else None)
            for path in _watched_files(data_dir)}


def assert_untouched(before: dict[Path, int | None], data_dir: Path) -> None:
    """Fail when any watched file was created, modified, or deleted."""
    after = sqlite_snapshot(data_dir)
    for path, before_ns in before.items():
        after_ns = after[path]
        if before_ns is None and after_ns is not None:
            raise AssertionError(
                f"A test created the real app-data database: {path}. Tests "
                "must patch Settings with a temporary data_dir."
            )
        if before_ns is not None and after_ns is None:
            raise AssertionError(f"A test deleted the real app-data database: {path}")
        if before_ns is not None and after_ns is not None and after_ns != before_ns:
            raise AssertionError(
                f"A test wrote the real app-data database: {path}. Tests must "
                "patch Settings with a temporary data_dir."
            )
