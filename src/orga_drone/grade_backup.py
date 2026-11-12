"""Pre-upgrade backup and restore for a future canonical grade database.

This module does not migrate grades and does not open a second database at
startup. Callers may take a verified SQLite backup and restore it. A failed
check leaves the destination file untouched.
"""

from __future__ import annotations

import gc
import hashlib
import json
import os
import sqlite3
import subprocess
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
    _sqlite_backup(source, temporary)
    if _integrity(temporary) != "ok":
        temporary.unlink(missing_ok=True)
        raise GradeBackupError("backup failed integrity check")
    digest = _sha256(temporary)
    user_version = _user_version(temporary)
    gc.collect()
    destination.write_bytes(temporary.read_bytes())
    temporary.unlink()
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
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
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

    The destination is replaced by a temporary sibling, so a failed copy does
    not leave a half-written database. Source media files are never touched.
    """
    manifest = verify_backup(directory)
    source = Path(directory) / str(manifest["file_name"])
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".restore")
    if temporary.exists():
        temporary.unlink()
    _sqlite_backup(source, temporary)
    if _sha256(temporary) != manifest["sha256"]:
        temporary.unlink(missing_ok=True)
        raise GradeBackupError("restored database checksum does not match")
    gc.collect()
    destination.write_bytes(temporary.read_bytes())
    temporary.unlink()
    return manifest


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
