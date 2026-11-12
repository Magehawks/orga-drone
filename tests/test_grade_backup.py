"""Backup and restore checks for the future canonical grade database."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from orga_drone.grade_backup import (
    GradeBackupError,
    create_backup,
    restore_backup,
    verify_backup,
)


def _seed(path: Path, marker: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE kept (marker TEXT)")
        connection.execute("INSERT INTO kept (marker) VALUES (?)", (marker,))
        connection.execute("PRAGMA user_version = 4")


def _marker(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT marker FROM kept").fetchone()
    assert row is not None
    return str(row[0])


def test_backup_verifies_and_restore_replaces_only_after_checksum(tmp_path: Path) -> None:
    source = tmp_path / "orga-drone.sqlite3"
    _seed(source, "before")
    manifest = create_backup(source, tmp_path / "recovery", app_version="2.3.3")
    assert manifest["sha256"]
    assert manifest["user_version"] == 4
    assert (tmp_path / "recovery" / "manifest.json").is_file()
    assert "source media" not in json.dumps(manifest)

    with sqlite3.connect(source) as connection:
        connection.execute("UPDATE kept SET marker = 'after'")
    assert _marker(source) == "after"

    restored = restore_backup(tmp_path / "recovery", source)
    assert restored["warning"].startswith("Restoring this backup")
    assert _marker(source) == "before"

    manifest_path = tmp_path / "recovery" / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(GradeBackupError, match="checksum"):
        verify_backup(tmp_path / "recovery")
    with pytest.raises(GradeBackupError, match="checksum"):
        restore_backup(tmp_path / "recovery", source)
    assert _marker(source) == "before"


def test_missing_source_does_not_create_a_backup(tmp_path: Path) -> None:
    with pytest.raises(GradeBackupError, match="missing"):
        create_backup(tmp_path / "absent.sqlite3", tmp_path / "recovery", app_version="2.3.3")
    assert not (tmp_path / "recovery" / "orga-drone.sqlite3").exists()
