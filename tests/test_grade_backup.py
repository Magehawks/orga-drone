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

    connection = sqlite3.connect(source)
    connection.execute("UPDATE kept SET marker = 'after'")
    connection.commit()
    connection.close()
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


def test_backup_and_restore_do_not_load_the_whole_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "orga-drone.sqlite3"
    _seed(source, "before")

    def refuse_read(self: Path) -> bytes:
        raise AssertionError(f"full read of {self}")

    def refuse_write(self: Path, data: bytes) -> int:
        raise AssertionError(f"full write of {self}")

    monkeypatch.setattr(Path, "read_bytes", refuse_read)
    monkeypatch.setattr(Path, "write_bytes", refuse_write)
    create_backup(source, tmp_path / "recovery", app_version="2.3.3")
    connection = sqlite3.connect(source)
    connection.execute("UPDATE kept SET marker = 'after'")
    connection.commit()
    connection.close()
    restore_backup(tmp_path / "recovery", source)
    assert _marker(source) == "before"


def test_open_connection_blocks_restore(tmp_path: Path) -> None:
    source = tmp_path / "orga-drone.sqlite3"
    _seed(source, "before")
    create_backup(source, tmp_path / "recovery", app_version="2.3.3")
    with sqlite3.connect(source) as connection:
        connection.execute("UPDATE kept SET marker = 'after'")
    held = sqlite3.connect(source)
    try:
        held.execute("BEGIN IMMEDIATE")
        with pytest.raises(GradeBackupError, match="open"):
            restore_backup(tmp_path / "recovery", source)
        row = held.execute("SELECT marker FROM kept").fetchone()
        assert row is not None and row[0] == "after"
        assert not (tmp_path / "orga-drone.sqlite3.restore").exists()
    finally:
        held.close()


def test_restore_replaces_a_closed_write_ahead_log(tmp_path: Path) -> None:
    source = tmp_path / "orga-drone.sqlite3"
    _seed(source, "before")
    create_backup(source, tmp_path / "recovery", app_version="2.3.3")
    live = tmp_path / "live.sqlite3"
    connection = sqlite3.connect(live)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("CREATE TABLE kept (marker TEXT)")
    connection.execute("INSERT INTO kept (marker) VALUES ('live-wal')")
    connection.commit()
    wal = Path(str(live) + "-wal")
    wal_bytes = wal.read_bytes()
    connection.close()
    wal.write_bytes(wal_bytes)
    assert wal.stat().st_size > 0
    restore_backup(tmp_path / "recovery", live)
    assert _marker(live) == "before"
    assert not Path(str(live) + "-wal").exists()


def test_backup_reads_committed_wal_pages(tmp_path: Path) -> None:
    source = tmp_path / "orga-drone.sqlite3"
    connection = sqlite3.connect(source)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("CREATE TABLE kept (marker TEXT)")
    connection.execute("INSERT INTO kept (marker) VALUES ('from-wal')")
    connection.commit()
    try:
        create_backup(source, tmp_path / "recovery", app_version="2.3.3")
    finally:
        connection.close()
    restored = tmp_path / "restored.sqlite3"
    restore_backup(tmp_path / "recovery", restored)
    assert _marker(restored) == "from-wal"


def test_failed_copy_and_replace_leave_the_live_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import orga_drone.grade_backup as grade_backup

    source = tmp_path / "orga-drone.sqlite3"
    _seed(source, "before")
    create_backup(source, tmp_path / "recovery", app_version="2.3.3")
    connection = sqlite3.connect(source)
    connection.execute("UPDATE kept SET marker = 'after'")
    connection.commit()
    connection.close()

    def fail_copy(source_path: Path, destination: Path) -> None:
        destination.write_bytes(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(grade_backup, "_stream_copy", fail_copy)
    with pytest.raises(OSError, match="disk full"):
        restore_backup(tmp_path / "recovery", source)
    assert _marker(source) == "after"
    assert not (tmp_path / "orga-drone.sqlite3.restore").exists()

    monkeypatch.undo()
    original = grade_backup._publish_file

    def fail_replace(staged: Path, destination: Path) -> None:
        if destination == source:
            raise GradeBackupError("could not replace the database")
        original(staged, destination)

    monkeypatch.setattr(grade_backup, "_publish_file", fail_replace)
    with pytest.raises(GradeBackupError, match="replace"):
        restore_backup(tmp_path / "recovery", source)
    assert _marker(source) == "after"
    assert not (tmp_path / "orga-drone.sqlite3.restore").exists()


def test_manifest_failure_is_repeat_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import orga_drone.grade_backup as grade_backup

    source = tmp_path / "orga-drone.sqlite3"
    _seed(source, "before")
    create_backup(source, tmp_path / "recovery", app_version="2.3.3")
    connection = sqlite3.connect(source)
    connection.execute("UPDATE kept SET marker = 'second'")
    connection.commit()
    connection.close()
    original = grade_backup._publish_file

    def fail_manifest(staged: Path, destination: Path) -> None:
        if destination.name == "manifest.json":
            raise GradeBackupError("could not replace the database")
        original(staged, destination)

    monkeypatch.setattr(grade_backup, "_publish_file", fail_manifest)
    with pytest.raises(GradeBackupError, match="manifest"):
        create_backup(source, tmp_path / "recovery", app_version="2.3.3")
    monkeypatch.undo()
    create_backup(source, tmp_path / "recovery", app_version="2.3.3")
    restore_backup(tmp_path / "recovery", source)
    assert _marker(source) == "second"
