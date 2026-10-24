# Discovery: large libraries, missing roots, and scan safety

Related to GitHub issue #94. This is an audit of the scanner that ships on
the `issue-86-studio-ken-burns` tip (`49b1612`). It does not change scan
behavior, and it does not add albums, incremental scan, or cloud sync.

Measured on 2026-10-24 with Python 3.12.3 on Windows 11 (10.0.26300),
AMD64 Family 25 Model 33, local NTFS under the user temp directory on `C:`.
The 10k pass shared the machine with other local work, so the wall times
below are a busy-machine observation, not a quiet-lab baseline.

## Question

Can a creator with a large library on a local disk, a USB volume, or a NAS
trust a full rescan when a source disappears, and is a 10k-file library
cheap enough to describe as supported?

## What was exercised

| Case | Stand-in | Real hardware |
| --- | --- | --- |
| Root missing before scan | Directory deleted after a successful index | No NAS unplug |
| Files gone after the catalog clear | Files deleted inside `clear_root_media`, then indexing continued | No mid-copy disconnect |
| I/O error during indexing | `parse_media_file` raised `OSError` after the first file | No SMB timeout storm |
| Volume comes back at a new path | Same bytes copied to a second folder | No drive-letter change on a real disk |
| Two copies, same identity | Two folders, same DJI filename, size, and timestamp | — |
| Scale | 1,000 and 10,000 tiny JPEGs; 100 stub MP4s | No 4K masters, no SRT tracks |

Photo fixture: one 8×8 JPEG (631 bytes) written under DJI names
(`DJI_YYYYMMDDHHMMSS_NNNN_D.JPG`) so `recorded_at` comes from the filename.
No GPS, so offline geocoding did not run. Video fixture: a 56-byte MP4-shaped
stub. `ffprobe` was not installed. Classification used the bundled ffmpeg at
`imageio_ffmpeg` (`ffmpeg-win-x86_64-v7.1.exe`).

A nonexistent UNC path `\\orga-drone-audit-no-host\share` returned
`Path.exists() == False` in 1.3 seconds on this PC. That single name is not
a stalled SMB session. The scanner still has no timeout around directory
walk or the 2 MB video-header read.

## How a scan works today

`scan_root()` in `src/orga_drone/scan/__init__.py`:

1. Resolve the root and `rglob` every file. Media extensions are kept in one
   list, then sorted.
2. `Database.clear_root_media()` deletes that root's `media`, `assets`,
   `flows`, and `sessions`.
3. Each file is parsed and inserted with its own committed SQLite connection
   (`upsert_asset`, `upsert_media`, `link_media_meta_for_path`,
   `link_studio_item_for_path`, `update_media_auto_tags`).
4. Flows and sessions are rebuilt.
5. `mark_root_scanned()` runs only after that work returns.

`media_meta` (stars, favorite, tags, notes) and `studio_clips` /
`studio_projects` are not deleted by `clear_root_media`. `media.id` is not
stable: a full rescan allocates new ids. Studio and favorites are keyed by
path plus `identity_key` (`filename|size|recorded_at`, SHA-256). See ADR 0001
and ADR 0004.

`Database.connect()` commits on success and does not set WAL.
`PRAGMA journal_mode` during the benchmark was `delete`. A 10k scan left a
`sqlite3-journal` file beside the database, which matches one fsyncing
commit per statement batch.

`scan_all_roots()` checks `Path.exists()` and, when the folder is gone,
records `{error: "missing"}` and does not call `scan_root()`.
`POST /library/{root_id}/scan` does not check. It always calls `scan_root()`.
`POST /library/add` checks that the folder exists, then starts `scan_root()`.

Scan jobs live in memory (`ScanJobStore`). One library scan runs at a time.
There is no cancel. A failed job stores
`"<ExceptionName>: scan could not be completed"` and the library page treats
`state=completed` as success, then reloads. The per-root `error: "missing"`
payload is not rendered.

`available` on a Studio clip means a `media` row exists for that path. It
does not mean the file is on disk. Thumbnails are built on first view
(`ensure_thumbnail`), not during the scan. Browse already pages at 50, 100,
or 200 items.

## Failure modes

### A missing folder, Scan all

Observed: two indexed photos, one favorite (stars 2, tag `nas`, notes), one
Studio clip. After the directory was removed, `scan_all_roots()` returned
`error: "missing"`. Media count stayed 2. The favorite row was unchanged.
The Studio clip stayed `available=true` because the `media` row was still
there. `last_scanned_at` stayed on the previous success.

Playback of those paths is a separate 404 (`File missing` on the media
routes). The catalog still claims the files.

### A missing folder, Scan one root

`Path.rglob("*")` on a missing directory yielded **zero files and no
exception**. `scan_root()` then cleared the root and finished as a normal
empty scan (0.02 s, all counts 0, no error).

Observed afterward:

| Store | Result |
| --- | --- |
| `media` / `assets` / flows / sessions | 0 rows |
| `media_meta` | Favorite, stars, tags, and notes still stored on the old path |
| Studio clip | Same path and identity, `available=false` |
| Studio project | Kept |
| Job outcome | Success, not failure |

The favorite is invisible in Browse because Browse joins `media_meta` to
`media`. The row is not deleted. A later scan of the **same path** with the
files present relinks by path (`link_media_meta_for_path` updates the
existing path row).

This is the highest-severity finding. Unplugging a USB disk or losing a NAS
mount, then pressing **Scan** on that root, deletes the indexed catalog for
the root and reports a completed scan.

### Files disappear after the clear

The directory was still present for discovery. `clear_root_media()` then
deleted the indexed rows, and the files were removed before parse.

`scan_root()` **succeeded** and indexed 4 photos, all `size_bytes=0`
(`parse_media_file` uses 0 when `exists()` is false). `last_scanned_at` was
updated. The favorite stayed on the same path, and its `identity_key`
**changed** to the size-0 key. The Studio clip stayed `available=true`
because a ghost `media` row matched the path, now with that new identity.

A later remount at a **different** path looks up orphans by identity. The
stored key is the empty-file key, so the real file (non-zero size) will not
match. Scanning the original path again, with the bytes back, rewrites the
key by path match. That second step was read from
`link_media_meta_for_path`, not re-timed.

### OSError after the clear

Four photos were indexed, with a favorite and a Studio clip on the first.
The next scan cleared the root, parsed one file, then raised
`OSError: simulated NAS disconnect`.

Observed: 1 media row left (new id), 3 catalog rows gone, favorite and Studio
clip for the rewritten file still `available=true`, `last_scanned_at`
unchanged because `mark_root_scanned()` sits after the loop. The HTTP job
wrapper would mark the job failed and hide the absolute path. The partial
catalog is already committed. There is no rollback to the pre-scan index.

A favorite that lived only on one of the three unindexed files would remain
in `media_meta` and disappear from Browse until a later full success. This
fixture only attached metadata to the file that was rewritten.

Killing the process mid-scan was not run. The same window follows from
commit-per-call: `clear_root_media` is durable before the first insert.

### Same files, second folder, old root still present

Copying two JPEGs to a new folder and scanning it while the old root remained
inserted a second pair of `media` rows. The favorite and the Studio clip
stayed on the old path. Identity relink requires the old path to be **absent
from `media`**. A stale root blocks the move.

### Old root removed, then the new folder scanned again

`remove_root()` cascades to `media` and `assets` (`ON DELETE CASCADE`).
`media_meta` and `studio_clips` have no such cascade. Immediately after
remove, the favorite and the Studio clip still pointed at the old path, and
the clip was not available.

The following scan of the new folder relinked both onto the new path
(stars 5, tag `letter`, notes `move`, Studio `available=true`). One file had
been curated, so the orphan path set had size 1. That is the safe rematch.

### Two folders, same identity

Two copies shared filename, size, and `recorded_at`. Each had its own
favorite and Studio clip. Both roots were removed. A third folder containing
the same file was scanned.

| Store | Result |
| --- | --- |
| Studio | Both clips stayed on the old paths, `source_media_id` null. `link_studio_item_for_path` refuses to guess when more than one orphan path shares the identity. Covered by `test_ambiguous_identity_key_stays_unavailable`. |
| Favorites | One `media_meta` row was moved onto the new path (the `amb-a` tag and the old path kept as notes). The other favorite stayed on the dead `amb-b` path. |

`link_media_meta_for_path` uses `fetchone()` with no uniqueness check. Studio
and favorites do not follow the same rule. Two curated copies can donate one
favorite to the wrong survivor.

## What a healthy rescan keeps

Same folder, three JPEGs, one favorite (stars 4, tags `sunset` and `alps`,
notes `keep me`), one Studio clip, one Title Card (`Arrival`).

| Item | After rescan |
| --- | --- |
| `media.id` | 1, 2, 3 became 4, 5, 6 |
| Favorite path, stars, tags, notes, identity | Unchanged |
| Studio clip id and path | Unchanged; `source_media_id` updated to the new media id; `available=true` |
| Title Card | Same id, null path, `available=true` |

That matches the existing tests around `clear_root_media` plus path relink
(`tests/test_media_meta.py`, `tests/test_studio.py`). Those tests call
`clear_root_media` directly. They do not call `scan_root` on a missing
directory.

## Benchmarks

Local temp, journal mode `delete`, geocode off. Python peak is
`tracemalloc` inside `scan_root` (allocator bytes, not the ffmpeg process
and not the SQLite page cache). A Windows working-set read returned 0 and is
omitted.

| Library | First scan | Rescan | DB file after first scan | Python peak | Browse 50 + count | Duplicate pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 JPEGs | 53.2 s | 53.5 s | 840 KB | 4.9 MB | 3.8 ms | 11 ms |
| 10,000 JPEGs | 737.9 s (12.3 min) | 1175.0 s (19.6 min) | 6.71 MB (7,032,832 bytes) | 48.8 MB | 8.6 ms | 86 ms |
| 100 stub MP4s | 19.1 s | 18.7 s | 232 KB | 2.2 MB | see note | 1 ms |

About 700 bytes of database per tiny photo, with no `track_json`. A DJI SRT
track stored on the `media` row would dominate this size; that shape was not
loaded.

One JPEG parsed in 1.6–1.9 ms. The 10k first scan averaged about 74 ms per
file of wall time, so almost all of the time is the index (about five
commits per photo, on the order of 50,000 commits). Writing the 10k files
took 6.3 s, which is small next to the scan.

The 10k rescan was slower than the first scan on this busy machine. Both are
full rebuilds. Neither is an incremental pass.

One stub video parsed in 0.10 s (0.03 s on a warm repeat) because ffmpeg is
started per file (`should_index_as_library_video`, 30 s subprocess timeout).
The header reader also reads up to 2 MB per video (`scan_video_header`).
At the measured ~0.19 s per stub, 10,000 videos are on the order of 30
minutes of process startup on this PC **before** reading real headers or
waiting on a NAS. That figure is an extrapolation, not a 10k-video run.

The 100 stubs were one second apart, so session grouping joined them into
one session (`sessions: 1`). Browse collapse then returned one row. The 8.6 ms
figure for 10k photos is the meaningful browse number: those files were not
grouped.

In-memory `attach_photos_to_sessions` for 2,000 videos and 8,000 photos took
0.9 s. Grouping is not what makes a 10k scan take minutes. The nested photo
walk is still O(sessions × photos) and would matter for a much larger GPS
library, after the commit cost is fixed.

Browse, duplicate detection, and the map were not the slow part at 10k
metadata-only rows. The map API loads every GPS point with no limit
(`list_geo_media`); this fixture had no GPS, so that path was not timed.
Thumbnails for a 10k grid are a second cost on first Browse, outside these
scan numbers.

A linear reading of the busy 74 ms/file rate is a bit over two hours for
100,000 local tiny photos. Treat that as a scaling warning, not a budget.

## What is already solid

- Scan all skips a missing root and leaves indexed rows, favorites, and
  Studio references in place.
- A normal rescan of an unchanged path keeps favorites, tags, notes, Studio
  clip identity, and Title Cards, and refreshes `source_media_id`.
- Studio relink refuses an ambiguous identity. That test already exists.
- Removing a library root does not delete `media_meta` or `studio_clips`.
- After the old root is gone, a unique identity relinks onto the new path.
- Browse paging at 50/100/200 is enough for a 10k metadata catalog. The
  10k page query was under 10 ms.
- Scan progress jobs already exist. They do not make the rescan incremental.
- The failed-job string does not include the absolute path.

## Smallest safe follow-up

Do these as separate issues when implementation starts. This audit does not
open them.

1. **Refuse `scan_root` when the folder is missing.** If `exists()` is false,
   return the same `error: "missing"` shape `scan_all_roots` already uses.
   Do not call `clear_root_media` or `mark_root_scanned`. Use that guard on
   `POST /library/{id}/scan`. This is the smallest change that stops a
   disconnected USB or NAS root from wiping its catalog.
2. **Roll back a scan that fails after the clear.** A mid-index `OSError`
   must leave the previous `media` / `assets` / flows / sessions readable.
   One transaction per root, or index-aside then swap. Do not fold this into
   an incremental scanner.
3. **Skip a file that is gone, and do not rewrite `identity_key` from a
   size of 0.** Ghost rows are why Studio stays "available" for a file the
   user cannot open, and why a later path change can miss the real file.
4. **Relink `media_meta` only when a single orphan path has that identity.**
   Same rule Studio already uses.
5. **Show skipped and failed roots on the library page.** `scan_all` already
   returns `error: "missing"`, and the page drops it. `available` should stay
   a database fact; the library screen needs an offline/missing state so a
   completed job is not read as "every file was read."
6. **A deliberate remount action.** The user points an offline root at the
   new folder. Implementation removes or suspends the old root's `media`
   rows, then scans, so unique favorites and Studio clips can move. No
   automatic drive-letter guess.
7. **A cheaper rescan, measured again.** WAL or one transaction, and skip
   files whose size and mtime are unchanged. Re-time 1k and 10k photos on a
   quiet machine, plus a few hundred real videos with headers (and SRT if
   present). The roadmap already lists incremental rescan as Next. The
   numbers here say the commit-per-file full rebuild is the cost, not Browse.
8. **Cancel, and a timeout on directory walk and header reads.** ffmpeg probe
   already stops at 30 s per file. `rglob` does not. One stuck share holds
   the only scan slot until the process exits.

Slices 1 and 2 are the safety gate. Slice 7 is the performance gate. Large
library support should wait until both are true on a quiet run, including a
root that is absent before scan and a root that errors during scan.

## Regression tests to add with those slices

Existing coverage stays: meta and Studio survive `clear_root_media`, and an
ambiguous Studio identity does not move.

Add with the implementation, not in this docs change:

| Test | Assert |
| --- | --- |
| `scan_root` and `POST /library/{id}/scan` on a deleted directory | Previous media count, favorite, tags, notes, and Studio `available` stay; `last_scanned_at` unchanged; result is `missing`, not success |
| `scan_all_roots` on a deleted directory | Already the safe path; lock it so a later edit cannot call `scan_root` anyway |
| Parse raises after N files | Pre-scan media ids (or count and paths) and a favorite on an unprocessed file are still browseable |
| Files removed after discovery | No `size_bytes=0` rows; favorite `identity_key` unchanged |
| Two `media_meta` rows, one new file, same identity | Neither favorite path changes |
| Unique identity, old root removed, new folder scanned | Favorite and Studio path follow the new file |
| Second folder scanned while the old root still has `media` rows | Favorite and Studio stay on the old path |

## Non-goals

Cloud sync, a new database, copying media, albums, and implementing the
slices above. No physical NAS was unplugged in this pass. A future benchmark
on a quiet machine and on a real share should replace the busy-machine wall
times before anyone publishes a duration claim.
