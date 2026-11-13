# Grade backup layout and rollback (#351)

Status: verified backup/restore helpers are shipping. Startup takes the backup
when a live database exists and writes
`recovery/pre-grade-migration/canonical-writes-enabled.json`. Canonical wrap and
grade publication require that marker. Startup still opens the live
`orga-drone.sqlite3` (no separate canonical database file yet).

## Files

All paths are under the existing data directory (`%APPDATA%\orga-drone` on
Windows, or `ORGA_DRONE_DATA_DIR` in tests). Source media is never in this
directory and is never copied.

| Path | Role |
|---|---|
| `orga-drone.sqlite3` | Live library. Unchanged by this step. |
| `recovery/pre-grade-migration/orga-drone.sqlite3` | SQLite backup API copy, taken before any future canonical migration. |
| `recovery/pre-grade-migration/manifest.json` | SHA-256, byte size, `user_version`, app version, UTC time, and the warning that restore discards later edits. |
| `recovery/pre-grade-migration/canonical-writes-enabled.json` | Present only after a verified backup. Gates wrap/publication APIs. |

No separate canonical database file is created in this step. Older executables
keep opening `orga-drone.sqlite3` and ignore the grade envelope; legacy color
setters refuse canonical clips (`CANONICAL_GUARD`).

## Permissions

`recovery/pre-grade-migration` is restricted to the current Windows user
(`icacls` removes inheritance and grants that user full control). On other
platforms the directory mode is `0700`. If the restriction fails, the backup
stops and does not publish a manifest.

## Rollback

1. Quit Orga Drone so no connection holds the live database.
2. Verify `manifest.json` against the backup file. A checksum or integrity
   failure aborts and leaves the live database in place.
3. Restore copies the verified backup to a sibling file, checks that sibling,
   then replaces `orga-drone.sqlite3` with `os.replace`. The copy is streamed.
   It is not loaded into memory, and it is not written into the live file.
4. An open connection or a Windows file lock aborts before that replace. A
   closed write-ahead log is checkpointed and removed first, so it cannot
   replay onto the restored file. A failed copy deletes the sibling and leaves
   the live database in place.
5. Edits made after the backup are gone. The manifest warning states that.
6. Do not delete or rewrite source media.

If the backup file is published and the manifest replace then fails, run the
backup again. The next run replaces both files. Restoring the backup discards
later edits, including any canonical grades written after the marker existed.

`tests/test_grade_backup.py` covers a round trip, a tampered checksum, an open
connection, a write-ahead log, a failed copy, a failed replace, and a second
backup after a failed manifest publish.
