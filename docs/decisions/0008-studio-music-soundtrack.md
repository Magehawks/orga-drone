# ADR 0008: Studio music as a read-only project soundtrack

- **Status:** Proposed
- **Date:** 2026-08-14
- **Deciders:** Issue #25

## Context

Studio MVP required one local music track in preview and MP4 export. The Music
lane was a session-global UI stub (`sessionStorage` + HTML file input) with no
persistable path and no encoder mix. Architecture rule 5 confines library
path operations under library roots. User music often lives in a Music folder
outside those roots. HTML `<input type="file">` cannot survive restart or feed
ffmpeg.

## Decision

1. Persist at most one soundtrack per project in `studio_audio_clips`
   (`lane='music'`), as a **read-only absolute file path** plus volume,
   fade-in/out, and loop. Unique index enforces one music row. The table is
   not `studio_clips` (wrong identity/relink model) and not columns on
   `studio_projects` (would block a later ordered collection / voice-over
   lane). Never copy the file into the library or app data as the edit model.
2. Document a **narrow exception** to library-root confinement: this path is
   a soundtrack reference, not library media. `/media/*`, rename, and merge
   stay root-confined. The client JSON **never** includes `file_path`;
   preview streams `GET /api/studio/projects/{id}/music/stream` from the DB
   path only.
3. Select the file with a native desktop open dialog (`FileDialog.OPEN`).
   Browser-only picking returns 503. PUT may pass a path after the picker
   (and in tests).
4. Mix after the existing concat: H.264 copy + AAC stereo 48 kHz via
   `amix` (`duration=first`, `normalize=0`) so source audio is kept when
   present and silence-padded clips stay silent except for music. Skip the
   mix when no music is configured (regression). Missing/unreadable/
   undecodable music fails the export loudly (`music_missing` /
   `music_unreadable` / `music_unsupported`). Loop is `-stream_loop`;
   longer-than-story music is trimmed to story duration.

## Alternatives considered

1. **HTML file input + blob** — no durable path; cannot export after restart.
2. **Copy music into `{data_dir}`** — treats the user’s file as an owned
   asset and complicates delete/replace.
3. **Store music as `studio_clips`** — would import into the library model
   and relink on rescan.
4. **Replace source audio with music-only** — drops phone/action-camera
   soundtracks as soon as music is added.

## Consequences

- Positive: One optional per-project track in preview and export; projects
  stay isolated; source video and music files are never modified.
- Negative / trade-offs: Off-root read of a user-chosen audio file;
  loud source audio mixed with music is not ducked; browser-only cannot
  pick a file; last-success / music history is not stored.
- Follow-up: ordered music collection (drop the unique index), voice-over
  lane, per-clip mixer / ducking, music in/out trim. UI for this issue
  stays one slot.
