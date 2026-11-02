# Release candidate validation - 2.3.1

Date: 2026-11-02

Status: **CONDITIONAL GO** for the manual Product Owner test. **NO-GO for
publication** until the conditions in [Publication gates](#publication-gates)
are met.

## Candidate

| | |
| --- | --- |
| Version | 2.3.1 |
| Audited `main` | `a1b485c51a49f37958006214eb90faad85c7c7a7` (merge of PR #250) |
| Test-build commit | `b2875fa5549a51764ee102b0dcf79220c89a9b8e` (audited `main` + PR #251) |
| Test-build branch | `fix/image-save-state-after-stale` |
| Pull request containing the P2 fix | [#251](https://github.com/Magehawks/orga-drone/pull/251) (open, mergeable) |

The test build includes the P2 save-state fix. `main` at `a1b485c` still has the
bug until PR #251 is merged.

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

Built from `b2875fa` with the existing onefolder PyInstaller spec.

| | |
| --- | --- |
| Version | 2.3.1 |
| Build commit | `b2875fa5549a51764ee102b0dcf79220c89a9b8e` |
| Bundle layout | `orga-drone.exe` plus `_internal/` |
| Templates, static, locales | Present |
| WebView2 Core assembly | Present |
| `Python.Runtime.dll` | Present |
| FFmpeg | GPL build copied over the imageio-ffmpeg binary |
| Third-party verdict | `GO`, `verify-zip` exit 0 |
| Zip size | 133,684,996 bytes |
| Zip SHA256 | `0929cf436665acd97545b7afd29c0b6a6dd32dfd401ddf9d81d9e18c26c34ad2` |
| Native launch | Window opened, title `orga-drone`, no `startup-crash.log` |
| WebView2 processes | 18 child processes during launch |

Artifacts are outside the repository at:

```text
C:\Users\Niwes\Projects\orga-drone-rc-artifacts\2.3.1-rc-pr250-fix251\
  orga-drone-windows-x64.zip
  orga-drone-windows-x64.zip.sha256
  release-build.txt
```

The native smoke test confirmed that the desktop shell starts with WebView2.
It did **not** exercise the native folder picker, soundtrack picker, native
Export Save dialog, a 1080p export, close/relaunch persistence, or
Mark-of-the-Web behavior. Those remain mandatory before publication and are
listed in `packaging/README.md`.

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

**Save state can show "saved" after a stale PATCH response.** When two image
adjustment writes interleave, a stale response kept `clip.dirty = true` but
still called `setSaved(true)`. The UI could therefore claim the clip was saved
while it was still dirty.

- Reproduced in browser E2E on `a1b485c`.
- Fixed in PR #251 at `b2875fa`.
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

The candidate is suitable for the manual Product Owner test. Do not publish a
release until all of the following are true:

1. Merge PR #251, or rebuild and re-test from `main` after the fix lands.
2. Run the mandatory Mark-of-the-Web smoke test from `packaging/README.md`:
   MOTW-marked zip, Explorer extraction into a path with parentheses, native
   desktop launch, native folder and soundtrack pickers, native Export Save
   dialog, a 1080p export, and close/relaunch persistence.
3. Record the final tested zip SHA256, commit, date, and outcome in the draft
   release notes.
4. Keep the GitHub Release notes-only. Do not attach the zip to a GitHub
   Release.

## Recommendation

**CONDITIONAL GO** for the manual Product Owner test using commit `b2875fa`.

The audited `main` commit is not publication-ready because PR #251 is still
open and the native MOTW checklist has not been completed. Do not publish,
tag, or merge automatically.
