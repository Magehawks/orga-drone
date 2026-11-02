# Release candidate validation - 2.3.2

Date: 2026-11-02

Status: The published `v2.3.1` artifact is **NO-GO** for Studio LUT playback.
The `2.3.2` candidate from `main` passes the automated validation below. The
manual Mark-of-the-Web checklist is still **NOT TESTED**.

## Candidate

| | |
| --- | --- |
| Version | 2.3.2 |
| Audited `main` | `42c7451` (merge of PR #252) |
| Test-build commit | `b6267ff64d9ad225057496b25d86b71ca399f565` (2.3.2 version bump) |
| Test-build branch | `fix/studio-lut-playback` |
| Real-time LUT playback fix | PR #231, already in `main`; absent from tag `v2.3.1` |

The reported Studio LUT playback blocker reproduces on tag `v2.3.1` and does
not reproduce on the `2.3.2` candidate. No new production code was needed for
the playback fix because `main` already contains PR #231.


## Environment

| | |
| --- | --- |
| OS | Windows 11, `10.0.26300` |
| Python | 3.12.3 |
| PyInstaller | 6.22.3 |
| Node / npm | 26.13.0 / 11.20.0 |
| Microsoft Edge | 156.0.4314.58 |
| Python test FFmpeg | imageio-ffmpeg bundled 7.1 and a temporary FFmpeg 9.0.2 binary |
| Test build FFmpeg | `packaging/third_party/ffmpeg-gpl/bin/ffmpeg.exe` |

All Python test runs used `PYTHONPATH=<worktree>\src` so that the worktree was
imported instead of the editable install of the original checkout.

## Results

### Static checks and tests

| Check | Result |
| --- | --- |
| `ruff check .` on `a1b485c` | Pass |
| MyPy on `a1b485c` | Pass, 72 source files |
| `npm run check:js` on `a1b485c` | Pass, 52 tests |
| `pytest --ignore=tests/test_pr_journey_smoke.py -q -rs` on `a1b485c` | 749 passed, 2 skipped, 68 warnings, 284.90 s |
| `pytest tests/test_pr_journey_smoke.py -q` on `a1b485c` | 1 passed, 2.72 s |
| `pytest tests/test_windows_third_party.py -q -rs` with the bundled 7.1 binary | 12 passed |
| `npm run check:js` on `b2875fa` | Pass, 52 tests |

The two skips in the full FFmpeg 9.0.2 run were:

- `tests/test_windows_third_party.py:205` - "Windows imageio-ffmpeg 7.1 binary is not installed"
- `tests/test_windows_third_party.py:218` - "Windows imageio-ffmpeg 7.1 binary is not installed"

Both were caused by forcing `IMAGEIO_FFMPEG_EXE` to FFmpeg 9.0.2. The same
module passes 12/12 against the bundled 7.1 binary. They are not product
failures.

The warnings are existing Starlette `TestClient` cookie deprecations and a
Pillow `Image.getdata` deprecation. No warning is new to this candidate.

### Browser end-to-end test

Playwright 1.64.1 drove Microsoft Edge (`channel: "msedge"`, headless) against
a real Uvicorn server and an isolated data directory. The test passed.

Verified flows:

- Start the packaged application code in browser mode on `127.0.0.1:8765`.
- Add and scan a synthetic library.
- Create a Studio project.
- Add a photo and a video, then switch between clips.
- Change image exposure, save, reload, and verify persistence.
- Import, activate, and deactivate a LUT.
- Change and reset HSL hue, set and reset a color-wheel point, change sharpen.
- Start and stop playback.
- Open the export dialog and check resolution options.

Console and network noise was limited to the expected `404 /favicon.ico` and
`503 /api/desktop/pick-open-file` (the browser has no native desktop picker).
There were no unexpected page errors, failed requests, or console errors after
filtering those expected cases.

The browser cannot complete the native Save dialog for an MP4. Export was
therefore validated through the existing export API rather than the browser
Save button.

### Studio LUT playback blocker

The release blocker was reproduced against a packaged EXE built from tag
`v2.3.1` (`e25aefe`). The package has no WebGL LUT renderer, so pause shows a
server-rendered LUT still while playback uses the ungraded video stream.

| Check | `v2.3.1` tag EXE | `2.3.2` candidate EXE |
| --- | --- | --- |
| Paused LUT frame | `(201, 98, 31)` | `(255, 77, 0)` |
| Playing frames at 3 times | `(34, 102, 204)` all three | `(255, 77, 0)` all three |
| Max / mean color difference, pause vs play | `173` / `114.67` | `0.0` / `0.0` |
| Pause after play / resume / seek while playing | LUT absent | `0.0` / `0.0` / `0.0` |
| LUT switch during play | n/a | `101` max / `33.67` mean |
| LUT deactivate during play | n/a | Original `(34, 102, 204)` |
| LUT re-enable during play | n/a | `0.0` vs paused reference |
| Clip switch, LUT active | n/a | Pause and play match |
| Main-thread long tasks | n/a | None |
| Frame gaps during playback | n/a | p95 `4.2 ms`, max `16.7 ms` |

The Windows E2E launched the actual PyInstaller onefolder (`orga-drone.exe`
plus `_internal`) and drove WebView2 over CDP. It captured visible
`Page.captureScreenshot` frames, not internal LUT state. The color comparison
uses a grid in the static background region so moving test objects cannot
produce a false match.

The candidate uses the original `/media/{id}/stream` source; it does not
create an FFmpeg playback proxy for this LUT-only clip.

### Export validation

| | |
| --- | --- |
| Project | 1 |
| Preset | 720p, `high` |
| Output | `rc-export/rc-e2e-export-2.mp4` |
| Size | 126,439 bytes |
| SHA256 | `931ECE9F56772803822CAFA18E7BC69C924C39FE9D88CFF9EBA493A677D89E2A` |
| Container / codec | MP4, H.264 |
| Duration | 6.04 s |
| Video | 1280x720, 30 fps |
| Audio | AAC, 48 kHz, stereo |
| Decode check | `decode_exit=0` |

### Windows test build

Built from `b6267ff` with the existing onefolder PyInstaller spec.

| | |
| --- | --- |
| Version | 2.3.2 |
| Build commit | `b6267ff64d9ad225057496b25d86b71ca399f565` |
| Bundle layout | `orga-drone.exe` plus `_internal/` |
| Templates, static, locales | Present |
| WebView2 Core assembly | Present |
| `Python.Runtime.dll` | Present |
| FFmpeg | GPL build copied over the imageio-ffmpeg binary |
| Third-party verdict | `GO`, `verify-zip` exit 0 |
| Zip size | 133,686,418 bytes |
| Zip SHA256 | `9fd9421f325b3a3de182a3c9c22d52c7575a6589d36aff0d5b1d91bd449faa7b` |
| Native launch | WebView2 window opened under CDP; no `startup-crash.log` |
| itch.io push | `magehawks/orga-drone:windows`, userversion `2.3.2` |

Artifacts are outside the repository at:

```text
C:\Users\Niwes\Projects\orga-drone-rc-artifacts\2.3.2\
  orga-drone-windows-x64.zip
  orga-drone-windows-x64.zip.sha256
  release-build.txt
```

The Windows E2E confirmed the desktop shell and WebView2 playback output. It
did **not** exercise the native folder picker, soundtrack picker, native
Export Save dialog, a 1080p export, close/relaunch persistence, or
Mark-of-the-Web behavior. Those remain **NOT TESTED** and are listed in
`packaging/README.md`.

### Data and source safety

- Test media, SQLite data, logs, and exports were written only to isolated
  temporary directories.
- The original checkout `C:\Users\Niwes\Projects\orga-drone` was not used for
  test data and was not modified.
- No source media was modified, moved, or deleted.
- Bundled database, `.env`, and source-media checks passed before zipping.

## Findings

### P0

None confirmed.

### P1

None confirmed.

### P2

**Studio LUT playback was missing from the published `v2.3.1` artifact.** The
tag predates PR #231. Pause used the server-rendered LUT still; playback used
the ungraded source video. The `2.3.2` candidate contains the WebGL playback
path already merged in `main`, and the measured pause/play difference is
`0.0`. No new production code change was required for this fix.

**Save state can show "saved" after a stale PATCH response.** When two image
adjustment writes interleave, a stale response kept `clip.dirty = true` but
still called `setSaved(true)`. The UI could therefore claim the clip was saved
while it was still dirty.

- Reproduced in browser E2E on `a1b485c`.
- Fixed in PR #251 at `b2875fa`; merged into `main` before the `2.3.2` build.
- `pendingClips` now records `{ clip, wrote }`; `setSaved(true)` runs only when
  a write actually happened.
- The stale response still triggers a preview refresh.
- Regression tests cover the stale response, dirty state, preview refresh, and
  image/ramp interleaving.
- JS checks pass on the fix.

### P3

- Browser-only expected errors: `404 /favicon.ico` and
  `503 /api/desktop/pick-open-file`. These are expected without a desktop
  picker and should not be presented as release failures.
- The full FFmpeg 9.0.2 run skips two Windows third-party tests because that
  module expects the 7.1 binary layout. The module passes with the bundled 7.1
  binary.

## Publication gates

The `2.3.2` candidate passed automated validation and was pushed to the
Draft/Restricted itch.io test path at the maintainer's request. Do not publish
a GitHub Release, tag, or public announcement until all of the following are
true:

1. PR #251 is merged in `main` (already required for the `2.3.2` build).
2. Run the mandatory Mark-of-the-Web smoke test from `packaging/README.md`:
   MOTW-marked zip, Explorer extraction into a path with parentheses, native
   desktop launch, native folder and soundtrack pickers, native Export Save
   dialog, a 1080p export, and close/relaunch persistence.
3. Record the final tested zip SHA256, commit, date, and outcome in the
   release notes.
4. Keep the GitHub Release notes-only. Do not attach the zip to a GitHub
   Release.

## Recommendation

**CONDITIONAL GO** for the `2.3.2` candidate using commit `b6267ff`.

The LUT playback blocker is fixed and proven on the real Windows EXE. The
manual Mark-of-the-Web/native-dialog checklist is still **NOT TESTED**, so the
release status stays conditional and must not be described as fully accepted.
Do not merge, tag, or publish a GitHub Release automatically.
