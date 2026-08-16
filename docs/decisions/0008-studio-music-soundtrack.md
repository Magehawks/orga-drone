# ADR 0008: Studio music as a sequential soundtrack playlist

- **Status:** Accepted
- **Date:** 2026-08-16
- **Deciders:** Issues #25 / #38; CTO Engineering Gate on PR #40

## Context

Studio MVP required local music in preview and MP4 export. The first shipping
slice stored **at most one** soundtrack per project (`studio_audio_clips`,
`lane='music'`) with a unique index, volume, fades, and loop. Issue #38 then
showed that coverage as a read-only span on the Story time canvas.

Human testing rejected a one-song-only model. The approved product is a
**sequential playlist** (`Song A → Song B → Song C`): ordered, contiguous from
Story t=0, not a DAW. Existing one-song projects must keep working.

## Decision

1. Persist an ordered soundtrack playlist in `studio_audio_clips`
   (`lane='music'`) as **read-only absolute file paths** plus per-song volume,
   fade-in/out, optional stored `duration_s`, and a loop flag. Drop unique
   index `idx_studio_audio_clips_one_music`. Keep non-unique
   `(project_id, lane, position)` with dense `position` `0..n-1`. Cap **8**
   songs (`STUDIO_MUSIC_MAX_TRACKS`). Never copy files into the library or app
   data as the edit model. Existing N=0/1 rows are not rewritten.
2. Document a **narrow exception** to library-root confinement: these paths are
   soundtrack references, not library media. `/media/*`, rename, and merge stay
   root-confined. Client JSON **never** includes `file_path`. Preview streams
   `GET /api/studio/projects/{id}/music/{clip_id}/stream` from the DB path only.
3. Select files with a native desktop open dialog (`FileDialog.OPEN`).
   Browser-only picking returns 503. POST may pass a path after the picker
   (and in tests). Add/replace/remove/reorder are playlist operations; Add
   lives outside the time lane (timeline toolbar).
4. Coverage uses the same Story time source as clips/ruler/playhead (`timeToX`,
   Fit/zoom). Render **N sequential spans** from t=0. Loop still stretches one
   song to Story end **only when N=1**. When N≠1, hide Loop in the Inspector
   and reject PATCH `loop` (`400 loop_single_only`); stored loop bits are
   ignored in preview, coverage, and export. Playlist-loop is Later.
5. Mix after the existing concat: H.264 copy + AAC stereo 48 kHz via `amix`
   (`duration=first`, `normalize=0`). N=1 + loop keeps one `-i` +
   `-stream_loop -1` and `build_music_amix_filter`. Otherwise concat N prepared
   segments (per-song volume and afade, then `atrim` to story) and `amix`.
   Skip the mix when the playlist is empty. Missing/unreadable/undecodable
   songs fail the export loudly before the graph is built.

## Alternatives considered

1. **HTML file input + blob** — no durable path; cannot export after restart.
2. **Copy music into `{data_dir}`** — treats the user’s file as an owned
   asset and complicates delete/replace.
3. **Store music as `studio_clips`** — would import into the library model
   and relink on rescan.
4. **Replace source audio with music-only** — drops phone/action-camera
   soundtracks as soon as music is added.
5. **Keep the unique one-song index and ship coverage first** — rejected after
   human test; the playlist is the same PR, not a follow-up merge.

## Consequences

- Positive: Optional sequential playlist in preview and export; projects stay
  isolated; source video and music files are never modified; one-song projects
  including loop keep their previous behavior.
- Negative / trade-offs: Off-root read of user-chosen audio files; loud source
  audio mixed with music is not ducked; browser-only cannot pick a file;
  ping-pong preview may leave a residual tens-of-ms gap at song boundaries.
- Explicit non-scope: overlapping tracks, arbitrary start times, waveforms,
  trim/slip, audio crossfades, mixer/ducking, per-song loop, playlist-loop,
  voice-over, Issue #39 Projects chrome.
