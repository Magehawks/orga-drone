# ADR 0007: Studio export open / reveal after completion

- **Status:** Proposed
- **Date:** 2026-08-14
- **Deciders:** Issue #22

## Context

Issue #17 shipped local Studio MP4 export with a desktop save dialog and an
in-memory job store. After a successful render the progress dialog stayed
open and the user had to locate the file by hand. Issue #22 asks for a
clear success state plus Open video / Show in folder, without an export
history, social upload, or mid-render cancel.

Browser-only mode cannot open OS file handlers. Windows is the shipping
desktop; other platforms must fail clearly rather than fake a reveal.

## Decision

1. Remember the last successful export in process memory
   (`ExportJobStore._last_success`: job id, output path, directory,
   filename, finished_at). Job TTL / finished-job eviction must not clear
   it. A later `fail()` must not wipe a previous success. No SQLite history.
2. Expose `POST /api/studio/export/open` and `POST /api/studio/export/reveal`.
   Ignore any client-supplied path. Act only on the last-success slot after
   validating an absolute `.mp4` that still exists as a file.
3. Implement OS actions in `desktop.py` (Windows: `os.startfile` /
   `explorer /select,`). Capability flags (`can_open_local_file` /
   `can_reveal_local_file`) gate the routes: unsupported platforms return
   503 with a stable `open_unavailable` / `reveal_unavailable` error.
   Missing files return 404 `missing_file`. Run the helpers in
   `asyncio.to_thread`.
4. On job `completed`, close the export dialog and show a dismissible Studio
   banner (`#studio-export-success`) that is **not** class `.flash` (the
   global toast auto-hides after ~6s). Hide the banner on dismiss, opening
   a new export, or navigation. Do not show it for failed or cancelled
   (pre-job) exports. Do not auto-hide the success banner.

## Alternatives considered

1. **Reuse `.flash` toasts** — auto-removed after ~6s, so Open / Reveal
   would disappear before the user can act.
2. **Accept a path in the POST body** — lets the client open arbitrary
   files; rejected in favor of the last-success slot.
3. **Persist export history in SQLite** — out of scope (future Exports
   area); would imply managing artifacts Orga Drone does not own.

## Consequences

- Positive: After export, users can watch or locate the MP4 on Windows
  without leaving Studio; source media and the exported file stay
  unmodified; project lifecycle is unchanged.
- Negative / trade-offs: Last-success is process-local (lost on restart);
  browser-only and non-Windows desktops get 503 rather than a fake reveal;
  Explorer `/select,` may exit 1 even on success.
- Follow-up: mid-render cancel and an Exports history remain later.
  Music-in-export is covered by ADR 0008.
