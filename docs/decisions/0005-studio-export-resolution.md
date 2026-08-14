# ADR 0005: Studio export resolution and encoder boundary

- **Status:** Accepted
- **Date:** 2026-08-06
- **Deciders:** Issue #17

## Context

GitHub Issue #17 asks for configurable Studio export resolution (720 / 1080 /
1440 / 2160), a recommended default of 1080 when justified by sources, a native
save dialog, and a codec-agnostic export configuration. Studio previously had
only an export UI stub (no render path).

## Decision

1. Derive available export heights from the highest **video** source height in
   the project (photos alone do not unlock a resolution). Classify heights to
   the nearest supported level without inventing upscaling beyond the project
   max.
2. Offer 720p → max; mark 1080 as **recommended** when available; otherwise
   default to the highest available level.
3. Persist optional `media.width` / `media.height` for caching; probe on demand
   when missing. Never modify source media files.
4. Keep user-facing export config codec-agnostic
   (`StudioExportConfig` / `StudioExportClip`). Encoder details live behind
   `StudioVideoEncoder`; the default adapter uses ffmpeg (H.264/AAC,
   `-preset veryfast`) internally and is not exposed in the UI.
5. Write via a temporary directory and move to the final path only on success;
   remember the last successful export directory in local app prefs; fall back
   to the OS Videos folder.
6. Desktop save dialog chooses the destination; browser mode cannot pick a path
   (clear error). Overwrite requires explicit confirmation.

## Alternatives considered

1. **Resolution UI without a render path** — fails destination / overwrite ACs
   and leaves a fake-success stub.
2. **Expose codec/bitrate in the same dialog** — explicitly out of scope for #17.
3. **Upscale below-source content to 4K** — rejected; options never exceed the
   project max justified by sources.

## Consequences

- Positive: Honest local MP4 export with resolution choice; sources untouched;
  encoder swappable later without UI churn.
- Negative / trade-offs: Music and mid-export cancel remain incomplete vs full
  Studio MVP; desktop save dialog required for destination picking.
- Follow-up: music-in-export, export cancel/abort, open/reveal exported file.
  Determinate export progress with elapsed/ETA/current clip label is Available now.
  Segment encodes force CFR 30fps + yuv420p so photo/video concat stays timeline-safe.
