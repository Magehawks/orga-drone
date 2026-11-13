"""Pre-upgrade backup and restore for the canonical grade database.

Callers take a verified SQLite backup and restore it. ``studio_grade_persistence``
enables canonical writes only after a verified backup exists. This module does
not migrate grades and does not select a database at startup. A failed check
leaves the destination file untouched.

Publication copies through a sibling file and ``os.replace``. The live
database is never overwritten in place. Restore requires a closed database:
an open connection or a Windows file lock aborts before the replace. A
write-ahead log on a closed database is checkpointed and removed so it cannot
replay onto the restored file.
"""

from __future__ import annotations

import gc
import hashlib
import json
import os
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

BACKUP_KIND = "pre-grade-migration-backup"
BACKUP_SCHEMA = 1
LIVE_DB_NAME = "orga-drone.sqlite3"
BACKUP_DIR_NAME = "recovery/pre-grade-migration"


class GradeBackupError(RuntimeError):
    """The backup or restore stopped before changing the destination."""


def backup_directory(data_dir: Path) -> Path:
    return Path(data_dir) / "recovery" / "pre-grade-migration"


def restrict_to_current_user(directory: Path) -> None:
    """Leave the backup readable by the current user only."""
    directory.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        directory.chmod(0o700)
        return
    user = os.environ.get("USERNAME", "").strip()
    if not user:
        raise GradeBackupError("backup directory owner is unknown")
    completed = subprocess.run(
        ["icacls", str(directory), "/inheritance:r", "/grant:r", f"{user}:(OI)(CI)F"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise GradeBackupError("backup directory permissions could not be restricted")


def create_backup(
    source: Path,
    directory: Path,
    *,
    app_version: str,
) -> dict[str, object]:
    """Copy ``source`` with the SQLite backup API and verify the copy."""
    source = Path(source)
    directory = Path(directory)
    if not source.is_file():
        raise GradeBackupError("source database is missing")
    restrict_to_current_user(directory)
    destination = directory / LIVE_DB_NAME
    temporary = directory / f"{LIVE_DB_NAME}.partial"
    if temporary.exists():
        temporary.unlink()
    try:
        _sqlite_backup(source, temporary)
        if _integrity(temporary) != "ok":
            raise GradeBackupError("backup failed integrity check")
        digest = _sha256(temporary)
        user_version = _user_version(temporary)
        _publish_file(temporary, destination)
    except (GradeBackupError, OSError):
        temporary.unlink(missing_ok=True)
        raise
    manifest = {
        "kind": BACKUP_KIND,
        "schema": BACKUP_SCHEMA,
        "source_name": source.name,
        "file_name": destination.name,
        "sha256": digest,
        "bytes": destination.stat().st_size,
        "user_version": user_version,
        "app_version": app_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "warning": "Restoring this backup discards edits made after it was taken.",
    }
    try:
        _publish_json(directory / "manifest.json", manifest)
    except (GradeBackupError, OSError) as exc:
        raise GradeBackupError(
            "backup database was staged but the manifest was not published; run the backup again"
        ) from exc
    verify_backup(directory)
    return manifest


def verify_backup(directory: Path) -> dict[str, object]:
    """Reject a backup whose checksum or integrity check does not match."""
    directory = Path(directory)
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise GradeBackupError("backup manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("kind") != BACKUP_KIND or manifest.get("schema") != BACKUP_SCHEMA:
        raise GradeBackupError("backup manifest is not a grade recovery backup")
    database = directory / str(manifest.get("file_name") or "")
    if not database.is_file():
        raise GradeBackupError("backup database is missing")
    if _sha256(database) != manifest.get("sha256"):
        raise GradeBackupError("backup checksum does not match")
    if _integrity(database) != "ok":
        raise GradeBackupError("backup failed integrity check")
    return dict(manifest)


def restore_backup(directory: Path, destination: Path) -> dict[str, object]:
    """Replace ``destination`` only after the backup verifies.

    The verified backup is copied to a sibling, checked again, then published
    with ``os.replace``. An open connection, a Windows lock, or a failed copy
    leaves the live database in place. Source media files are never touched.
    """
    manifest = verify_backup(directory)
    source = Path(directory) / str(manifest["file_name"])
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _prepare_destination(destination)
    temporary = destination.with_name(destination.name + ".restore")
    if temporary.exists():
        temporary.unlink()
    try:
        _stream_copy(source, temporary)
        if _sha256(temporary) != manifest["sha256"]:
            raise GradeBackupError("restored database checksum does not match")
        if _integrity(temporary) != "ok":
            raise GradeBackupError("restored database failed integrity check")
        _publish_file(temporary, destination)
    except (GradeBackupError, OSError):
        temporary.unlink(missing_ok=True)
        raise
    for suffix in ("-wal", "-shm"):
        Path(str(destination) + suffix).unlink(missing_ok=True)
    return manifest


def _stream_copy(source: Path, destination: Path) -> None:
    """Copy without reading the whole file into memory."""
    with source.open("rb") as incoming, destination.open("wb") as outgoing:
        for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
            outgoing.write(chunk)
        outgoing.flush()
        os.fsync(outgoing.fileno())


def _publish_file(staged: Path, destination: Path) -> None:
    """Replace ``destination`` atomically. A failure leaves it unchanged.

    Windows refuses the replace while the destination is open. This does not
    fall back to writing into the live file.
    """
    error: OSError | None = None
    for _attempt in range(3):
        gc.collect()
        if destination.exists() and _destination_is_locked(destination):
            time.sleep(0.05)
            continue
        try:
            os.replace(staged, destination)
            return
        except PermissionError as exc:
            error = exc
            time.sleep(0.05)
    if _destination_is_locked(destination):
        raise GradeBackupError("database is open; close it before restore") from error
    raise GradeBackupError("could not replace the database") from error


def _destination_is_locked(path: Path) -> bool:
    """True when Windows will not let us replace ``path``.

    SQLite can keep a file handle after its lock is released. ``os.replace``
    then fails even though a new SQLite connection would succeed. An exclusive
    open detects that handle. Other platforms rely on ``os.replace`` itself.
    """
    if os.name != "nt" or not path.exists():
        return False
    import ctypes
    from ctypes import wintypes

    windll_factory = getattr(ctypes, "WinDLL", None)
    if windll_factory is None:
        return False
    kernel32 = windll_factory("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.CreateFileW(str(path), 0x80000000 | 0x40000000, 0, None, 3, 0x80, None)
    if handle == wintypes.HANDLE(-1).value:
        return True
    kernel32.CloseHandle(handle)
    return False


def _publish_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        _publish_file(temporary, path)
    except (GradeBackupError, OSError):
        temporary.unlink(missing_ok=True)
        raise


def _prepare_destination(destination: Path) -> None:
    """Refuse an open database, then drop a closed write-ahead log.

    Checkpointing a closed database only commits its own WAL. It does not
    change application rows. The log is removed before the replace so SQLite
    cannot replay it onto the restored file.
    """
    if not destination.is_file():
        return
    connection = sqlite3.connect(destination, timeout=0.2)
    try:
        connection.execute("BEGIN EXCLUSIVE")
        connection.rollback()
    except sqlite3.OperationalError as exc:
        raise GradeBackupError("database is open; close it before restore") from exc
    finally:
        connection.close()
    wal = Path(str(destination) + "-wal")
    if not wal.exists():
        Path(str(destination) + "-shm").unlink(missing_ok=True)
        return
    connection = sqlite3.connect(destination, timeout=0.2)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError as exc:
        raise GradeBackupError("database is open; close it before restore") from exc
    finally:
        connection.close()
    if wal.exists() and wal.stat().st_size > 0:
        raise GradeBackupError("write-ahead log is still open")
    wal.unlink(missing_ok=True)
    Path(str(destination) + "-shm").unlink(missing_ok=True)


def _sqlite_backup(source: Path, destination: Path) -> None:
    src = sqlite3.connect(source)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    except sqlite3.Error as exc:
        raise GradeBackupError("sqlite backup failed") from exc
    finally:
        dst.close()
        src.close()


def _integrity(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    if row is None:
        return ""
    return str(row[0])


def _user_version(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute("PRAGMA user_version").fetchone()
    finally:
        connection.close()
    return int(row[0]) if row is not None else 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
