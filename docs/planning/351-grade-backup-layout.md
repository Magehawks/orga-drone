# Grade backup layout and rollback (#351)

Status: procedure and verified backup/restore helpers. Canonical grade writes
stay disabled. Startup does not switch databases yet.

## Files

All paths are under the existing data directory (`%APPDATA%\orga-drone` on
Windows, or `ORGA_DRONE_DATA_DIR` in tests). Source media is never in this
directory and is never copied.

| Path | Role |
|---|---|
| `orga-drone.sqlite3` | Live library. Unchanged by this step. |
| `recovery/pre-grade-migration/orga-drone.sqlite3` | SQLite backup API copy, taken before any future canonical migration. |
| `recovery/pre-grade-migration/manifest.json` | SHA-256, byte size, `user_version`, app version, UTC time, and the warning that restore discards later edits. |

No canonical database file is created. A future write may use a separate file
only after this backup verifies. Older executables keep opening
`orga-drone.sqlite3` until that separate file exists and startup enforcement
is switched on.

## Permissions

`recovery/pre-grade-migration` is restricted to the current Windows user
(`icacls` removes inheritance and grants that user full control). On other
platforms the directory mode is `0700`. If the restriction fails, the backup
stops and does not publish a manifest.

## Rollback

1. Quit Orga Drone.
2. Verify `manifest.json` against the backup file. A checksum or integrity
   failure aborts and leaves the live database in place.
3. Restore replaces `orga-drone.sqlite3` only after that check.
4. Edits made after the backup are gone. The manifest warning states that.
5. Do not delete or rewrite source media.

`tests/test_grade_backup.py` covers a successful round trip and a tampered
checksum that must not replace the live database.
