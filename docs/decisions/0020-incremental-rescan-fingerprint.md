# ADR 0020: Skip unchanged media on rescan

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** Issue #96 (discovery #94 waived by the product owner)

## Context

A library rescan used to delete and recreate every asset and media row for a
root, then parse every file again. That spends most of its time on metadata
extraction (EXIF, container probe, SRT) for files that did not change.
Large folders, including NAS archives, pay that cost on every scan.

Issue #96 asks for a documented safe fingerprint and for added, changed, and
deleted files to reconcile, while user tags, favorites, and Studio references
survive. It does not name the fingerprint. Hashing every large video is an
explicit non-goal. An unlistable root keeps its catalog and is marked offline
(issue #95). The fingerprint skip applies only after that root can be listed.

## Decision

1. The skip signal is the indexed asset's **size in bytes** plus its
   **filesystem mtime** (`st_size` and `st_mtime`, already stored on
   `assets`). Issue #96 did not specify a fingerprint; this pair is the one
   this slice uses.
2. When both values match the file on disk, `parse_media_file` is not called.
   The media id stays. SRT/LRF flags and Live Photo pairing are still refreshed
   from the discovered filenames, because those can change without the video
   bytes changing.
3. New files and files whose size or mtime differ are parsed and upserted in
   place (same path keeps the same media id).
4. After a completed walk of a root that is still readable, asset and media
   rows whose paths were not found are removed. Files on disk, `media_meta`,
   and Studio clips are not deleted. A missing or unreadable root, or a walk
   that raises `OSError`, does not remove index rows.
5. Flows and sessions are still rebuilt at the end of a successful scan.

## Alternatives considered

1. **Content hash of every file** — would detect same-size edits that keep
   mtime, but issue #96 excludes hashing large videos.
2. **Keep clearing the root, then skip parse** — would still drop media ids
   and force Studio relink on every scan.
3. **Retain a browsable snapshot of an unavailable root as a new catalog
   mode** — that is issue #95, not this slice.

## Consequences

- Positive: a no-op rescan does not re-extract metadata. Media ids for
  unchanged and in-place updates stay stable, so favorites and Studio
  `source_media_id` values remain attached.
- Negative / trade-offs: size + mtime can miss a same-size rewrite that also
  restores mtime. The directory walk and flow/session rebuild still run.
  A partial listing of a root that is still readable can drop index rows for
  paths the walk did not return.
- Follow-up work: cheaper directory walks, or a stronger change signal if a
  real archive shows missed edits. Not a content hash of every video unless a
  later issue asks for it.
