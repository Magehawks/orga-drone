"""Unit tests for the app-data isolation guard (tests/appdata_guard.py).

The guard itself must be deterministic and must never touch the real
database — every check here runs against temporary directories.
"""

from __future__ import annotations

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


def test_snapshot_absent_is_none(tmp_path: Path) -> None:
    assert sqlite_snapshot(tmp_path) is None


def test_snapshot_returns_mtime(tmp_path: Path) -> None:
    path = _touch(tmp_path)
    assert sqlite_snapshot(tmp_path) == path.stat().st_mtime_ns


def test_untouched_passes_without_file(tmp_path: Path) -> None:
    assert_untouched(None, tmp_path)  # nothing before, nothing after


def test_untouched_passes_with_same_mtime(tmp_path: Path) -> None:
    path = _touch(tmp_path)
    assert_untouched(path.stat().st_mtime_ns, tmp_path)


def test_created_file_fails(tmp_path: Path) -> None:
    _touch(tmp_path)
    with pytest.raises(AssertionError) as excinfo:
        assert_untouched(None, tmp_path)
    assert "created" in str(excinfo.value)


def test_modified_file_fails(tmp_path: Path) -> None:
    path = _touch(tmp_path)
    before = path.stat().st_mtime_ns
    import os
    import time as time_module

    # Force a distinct mtime (same-second filesystems would compare equal).
    future = time_module.time() + 10
    os.utime(path, ns=(int(future * 1e9), int(future * 1e9)))
    assert path.stat().st_mtime_ns != before
    with pytest.raises(AssertionError) as excinfo:
        assert_untouched(before, tmp_path)
    assert "wrote" in str(excinfo.value)


def test_deleted_file_fails(tmp_path: Path) -> None:
    path = _touch(tmp_path)
    before = path.stat().st_mtime_ns
    path.unlink()
    with pytest.raises(AssertionError) as excinfo:
        assert_untouched(before, tmp_path)
    assert "deleted" in str(excinfo.value)


def test_real_default_dir_ignores_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORGA_DRONE_DATA_DIR", str(Path("H:") / "should-be-ignored"))
    resolved = real_default_data_dir()
    assert "should-be-ignored" not in str(resolved)
    # The override is restored for the rest of the process.
    import os

    assert os.environ.get("ORGA_DRONE_DATA_DIR") == str(Path("H:") / "should-be-ignored")


def test_real_default_dir_is_the_documented_platform_location() -> None:
    """The guarded directory matches the documented runtime data location
    (docs/ARCHITECTURE.md): Windows %APPDATA%/orga-drone."""
    resolved = real_default_data_dir()
    if __import__("os").name == "nt":
        assert resolved.name == "orga-drone"
        assert "AppData" in str(resolved) or "Roaming" in str(resolved)
