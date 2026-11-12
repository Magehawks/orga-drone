"""Unit tests for the app-data isolation guard (tests/appdata_guard.py).

The guard itself must be deterministic and must never touch the real
database — every check here runs against temporary directories.
"""

from __future__ import annotations

import os
import time as time_module
from pathlib import Path

import pytest

from tests.appdata_guard import (
    DB_FILENAME,
    assert_untouched,
    real_default_data_dir,
    sqlite_snapshot,
)


def _touch(data_dir: Path) -> Path:
    path = data_dir / DB_FILENAME
    path.write_bytes(b"sqlite-fixture")
    return path


def _force_mtime(path: Path, seconds_ahead: float = 10.0) -> int:
    future = time_module.time() + seconds_ahead
    os.utime(path, ns=(int(future * 1e9), int(future * 1e9)))
    return path.stat().st_mtime_ns


def test_snapshot_absent_is_none(tmp_path: Path) -> None:
    snapshot = sqlite_snapshot(tmp_path)
    assert all(value is None for value in snapshot.values())
    assert (tmp_path / DB_FILENAME) in snapshot  # the base file is watched


def test_snapshot_includes_wal_and_shm(tmp_path: Path) -> None:
    _touch(tmp_path)
    wal = tmp_path / (DB_FILENAME + "-wal")
    shm = tmp_path / (DB_FILENAME + "-shm")
    wal.write_bytes(b"wal")
    shm.write_bytes(b"shm")
    snapshot = sqlite_snapshot(tmp_path)
    assert snapshot[wal] == wal.stat().st_mtime_ns
    assert snapshot[shm] == shm.stat().st_mtime_ns


def test_untouched_passes_without_files(tmp_path: Path) -> None:
    assert_untouched(sqlite_snapshot(tmp_path), tmp_path)


def test_untouched_passes_with_same_mtimes(tmp_path: Path) -> None:
    path = _touch(tmp_path)
    before = sqlite_snapshot(tmp_path)
    assert before[path] == path.stat().st_mtime_ns
    assert_untouched(before, tmp_path)


def test_created_base_file_fails(tmp_path: Path) -> None:
    before = sqlite_snapshot(tmp_path)
    _touch(tmp_path)
    with pytest.raises(AssertionError) as excinfo:
        assert_untouched(before, tmp_path)
    assert "created" in str(excinfo.value)


def test_created_wal_fails(tmp_path: Path) -> None:
    before = sqlite_snapshot(tmp_path)
    (tmp_path / (DB_FILENAME + "-wal")).write_bytes(b"wal")
    with pytest.raises(AssertionError) as excinfo:
        assert_untouched(before, tmp_path)
    assert "created" in str(excinfo.value)


def test_modified_base_file_fails(tmp_path: Path) -> None:
    path = _touch(tmp_path)
    before = sqlite_snapshot(tmp_path)
    _force_mtime(path)
    assert path.stat().st_mtime_ns != before[path]
    with pytest.raises(AssertionError) as excinfo:
        assert_untouched(before, tmp_path)
    assert "wrote" in str(excinfo.value)


def test_modified_wal_fails(tmp_path: Path) -> None:
    _touch(tmp_path)
    wal = tmp_path / (DB_FILENAME + "-wal")
    wal.write_bytes(b"wal")
    before = sqlite_snapshot(tmp_path)
    _force_mtime(wal)
    with pytest.raises(AssertionError) as excinfo:
        assert_untouched(before, tmp_path)
    assert "wrote" in str(excinfo.value)


def test_deleted_file_fails(tmp_path: Path) -> None:
    path = _touch(tmp_path)
    before = sqlite_snapshot(tmp_path)
    path.unlink()
    with pytest.raises(AssertionError) as excinfo:
        assert_untouched(before, tmp_path)
    assert "deleted" in str(excinfo.value)


def test_real_default_dir_ignores_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORGA_DRONE_DATA_DIR", str(Path("H:") / "should-be-ignored"))
    resolved = real_default_data_dir()
    assert "should-be-ignored" not in str(resolved)
    # The override is restored for the rest of the process.
    assert os.environ.get("ORGA_DRONE_DATA_DIR") == str(Path("H:") / "should-be-ignored")


def test_real_default_dir_is_the_documented_platform_location() -> None:
    """The guarded directory matches the documented runtime data location
    (docs/ARCHITECTURE.md): Windows %APPDATA%/orga-drone."""
    resolved = real_default_data_dir()
    if os.name == "nt":
        assert resolved.name == "orga-drone"
        assert "AppData" in str(resolved) or "Roaming" in str(resolved)


def test_session_env_points_to_temporary_directory() -> None:
    """The pytest session's ORGA_DRONE_DATA_DIR (set at conftest import,
    before any orga_drone import) must be a temporary directory — never the
    platform-default app data location."""
    from orga_drone.config import _default_data_dir, settings

    session_dir = Path(os.environ["ORGA_DRONE_DATA_DIR"])
    assert "orga-drone-pytest-appdata-" in session_dir.name
    # Every settings instance and module binding resolves inside it.
    assert Path(settings.data_dir) == session_dir
    assert Path(_default_data_dir()) == session_dir
    # The REAL platform-default location is elsewhere (and watched by the
    # detective fixture, not used by the session).
    real = real_default_data_dir()
    assert real != session_dir
