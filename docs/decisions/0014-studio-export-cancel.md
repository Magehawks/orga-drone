# ADR 0014: Studio export cancellation

- **Status:** Accepted
- **Date:** 2026-10-23
- **Deciders:** Issue #88

## Context

A Studio MP4 export runs in a background thread and drives ffmpeg. The export
dialog had a Cancel button, but while an export was running that button only
closed the dialog and was disabled. ffmpeg kept writing. A long or mistaken
export could only be stopped by closing Orga Drone.

## Decision

1. **Cancel export** stays available during an active export. It asks the
   running job to stop and kills the current ffmpeg process. The dialog stays
   open until the job reports `cancelled`. That state is not success.
2. The finished MP4 is published with `os.replace` only after the encode
   succeeds. Cancellation deletes the export temp directory and any
   `.partial` file this run created. It does not delete or replace a file
   that was already in the destination.
3. The Studio project is not modified. When the job leaves the active state,
   another export can start in the same process.

## Alternatives considered

1. **Close the dialog only** — leaves ffmpeg running.
2. **Delete the destination on cancel** — would remove a file the user already
   had if the name collides with an overwrite.

## Consequences

- Cancellation is bounded by killing ffmpeg, not by waiting for the current
  clip to finish.
- A file that was already replaced into the destination counts as a finished
  export. Cancel after that moment does not roll it back.
