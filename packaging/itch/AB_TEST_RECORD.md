# A → B itch.io update record

**Status: NOT RUN.**

This repository commit documents the channel and refuses an unsafe upload. It
does not upload to itch.io, and it does not install the itch.io desktop app.
Do not treat this file as evidence that an update was tested.

## Why it was not run

- Version B (userversion `1.10.0`, image correction and timed overlays) is not
  buildable here. Timed overlays are issue #78 and are not on `main`.
  `__version__` is still `1.9.0`, which is Version A's identifier.
- A public or unscoped upload is not an acceptable substitute. The process
  stops when a Draft or Restricted project is not available.
- No itch.io credentials are used by `packaging/itch_channel.py`.

Local checks that did run live in `tests/test_itch_channel.py`: onefolder
layout, baseline zip hash guard, public-visibility refusal, Version B refusal
on this tree, and a simulated install-folder replace that leaves a database
and a media file unchanged.

## Fill this in only after a real restricted test

| Field | Value |
|-------|--------|
| Version A userversion | `1.9.0` |
| Version A commit | `9eb28b0` |
| Version A zip SHA256 | `DB79717444EDD34A26DD43BE53E4420FCDA3075D4430F3F78292640716B70D88` |
| Version A smoke test (MOTW zip, Explorer, parentheses path) | not run for this issue |
| Version B userversion | `1.10.0` |
| Version B commit | not built |
| Version B zip SHA256 | not built |
| itch.io project visibility | must be Draft or Restricted; not recorded |
| Channel | `windows-x64-test` |
| Windows version of the clean test PC | not recorded |
| itch.io app version | not recorded |
| Date | |
| Tester | |

### Results

- [ ] A installed only through the itch.io desktop app
- [ ] Library folder and Studio project created on A and still present after B
- [ ] Original media files unchanged
- [ ] Settings (`theme.json`, `app_prefs.json`) still present
- [ ] Native window, folder picker, soundtrack picker, MP4 save dialog
- [ ] Studio preview and an MP4 export succeed on B
- [ ] Image correction persists and is visible in preview and export
- [ ] Timed overlays persist and are visible in preview and export
- [ ] The app applied B without a hand-copied exe
- [ ] Database copy taken before B is stored outside the install folder
- [ ] Interrupted-update recovery path tried or explicitly skipped, with notes
- [ ] Page was still Draft or Restricted after both uploads

### Notes

Write what failed, the rollback push if any, and whether the saved
`orga-drone.sqlite3` was restored. Leave the checkboxes empty until then.
