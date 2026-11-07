# Pull request end-to-end checks

How a pull request shows an automated pass through the local app, and which
checks stay with a person.

Orga Drone is a local FastAPI app with an optional pywebview (WebView2) window.
Media stays on disk. The Ubuntu pull-request runner cannot open a Windows
desktop; a separate Windows job tests the packaged app.

## Risk-based local checks

Choose checks for the changed behavior and explain the risk in the PR. Small
local check sets do not remove CI requirements. Full local suites are useful
for broad changes, not mandatory for every small edit.

- **Low risk — docs or UI copy/layout without logic changes:** review the diff,
  links, template/config syntax and DE/EN consistency as applicable. For UI work,
  check the affected rendering/interaction. No full Python suite is required just
  because a Markdown file changed. UI changes affecting playback/state are higher risk.
- **Medium risk — logic:** run focused regressions and relevant route/module
  integration tests. For Python changes, run Ruff and relevant MyPy checks. For
  Studio JS or JS test changes, run `npm run check:js`; it remains scoped to
  migrated modules/tests for lint and format. Legacy JS changes need relevant
  behavioral tests even though the monolith is outside that lint scope.
- **High risk — playback/audio/proxy, export, database/rescan, security or
  packaging:** focused regressions plus appropriate integration/packaged evidence
  for the affected boundary. For example, real FFmpeg decoding and source-byte
  checks for export, persistence/rescan tests for data, confinement/Host/Origin
  tests for security, and the Windows EXE/WebView2 harness for packaging. Explain
  what the evidence proves and any missing environment/media coverage. Do not
  substitute an HTTP-only smoke for desktop behavior. If required evidence is
  unavailable, keep it unresolved and obtain it before merge.

At release-candidate stage, run full automated validation and the relevant
packaged, real-media editing/export and Windows/MOTW checks. The Product Owner
records explicit release approval. Periodic real DJI testing runs separately
from routine develop merges and files bug issues; an issue may explicitly require
additional targeted manual evidence. See [AGENT_WORKFLOW.md](AGENT_WORKFLOW.md).

Report commands/results, skips and limitations honestly. Do not silently accept
failures or count skipped/missing required coverage as passed. Existing CI checks,
security gates, main admission and human release controls remain unchanged.

## CI coverage by branch

The **CI** workflow (`.github/workflows/ci.yml`) runs on `pull_request`:

It also runs these same checks on pushes to `main` and `develop`. The separate
**Main admission policy** check requires these checks, the packaged **Windows
packaged E2E** evidence, and an independent reviewer or explicit owner
authorization. It does not configure branch protection. See the
[branch migration runbook](BRANCH_MIGRATION.md#pr-b-implemented-pre-cutover-guard-and-administrator-configuration).

| Check | What it does |
| --- | --- |
| **Ruff, MyPy and unit tests** | `ruff check .`, `mypy src packaging/itch_channel.py packaging/windows_third_party.py packaging/main_admission.py packaging/packaged_e2e.py packaging/e2e/windows_e2e.py`, then `pytest` for unit and route tests. This step skips `tests/test_pr_journey_smoke.py` so a journey failure is reported by the check below. |
| **JavaScript lint, format and tests** | `npm ci`, `npm run lint:js`, `npm run format:check`, `npm run test:js` on Node 22. No browser and no product data. |
| **App journey smoke** | `pytest tests/test_pr_journey_smoke.py` |
| **Windows packaged E2E** (PRs to `main` only) | Builds the onefolder ZIP on `windows-latest`, extracts it, and drives the real EXE/WebView2 over CDP with synthetic media. |

A local `pytest` from the repo root runs the unit tests **and** the journey
file. Install dev tools with `pip install -e ".[dev]"`.

The **Windows release** workflow does not run on pull requests. It calls this
CI workflow and builds a zip only after its checks pass. Publishing that zip
still waits for the human Mark-of-the-Web checklist in `packaging/README.md`.

## What the journey smoke runs

The smoke builds a temporary data directory and one generated JPEG (Pillow).
It talks to the app with FastAPI’s `TestClient` (the same process, no browser):

1. `GET /health` returns `status: ok` and a version.
2. The UI language cookie is English.
3. Library starts without the fixture folder.
4. `POST /library/add` indexes that folder; the test polls `GET /api/scan-jobs/{id}` until the scan completes with one photo.
5. Library, Browse, and the media detail page show the file. Browse **Ask** (`photos`) and `POST /api/search` find it.
6. A Studio project is created and opened. The Story is empty, then the photo is added, then **Clear Studio** removes the clip.
7. Dashboard, Map, and Duplicates respond. After clear, Browse still lists the photo and the JPEG is still on disk.

A failure is a red **App journey smoke** check on the pull request. Open the
job log for the pytest assertion. The job summary states the result and points
back here.

## What the Windows packaged E2E runs

[`windows-e2e.yml`](../.github/workflows/windows-e2e.yml) runs on every
`opened`, `synchronize`, `reopened`, and `ready_for_review` PR to `main`. It
checks out the PR merge commit, builds the existing PyInstaller onefolder app,
extracts the ZIP, and launches the packaged `orga-drone.exe` with the real
WebView2 runtime. The harness:

1. Confirms startup, `/health`, and the rendered Home page in WebView2.
2. Imports a synthetic JPEG and a generated 2 s MP4, then scans and searches them.
3. Opens Browse and the media detail view.
4. Creates and opens a Studio project, adds the video and photo, and renders `/studio`.
5. Plays the video preview and checks `currentTime` advances with no crash.
6. Edits a photo clip, reloads, relaunches, and verifies the edit persists.
7. Exports a 720p MP4, decodes it, checks duration/order, and verifies source files are unchanged.
8. Exports the library photo through the packaged image-export API and verifies the image decodes.
9. Writes `evidence.json` bound to the head/base, PR merge SHA/tree, run/attempt,
   tested ZIP SHA-256/size, and the uploaded Actions artifact digest/size;
   uploads it separately from the candidate ZIP and diagnostic screenshots/logs
   for 30 days.

Admission rejects missing, failed, cancelled, skipped, expired, malformed,
partial-rerun, older-green, or mismatched evidence. The workflow and harness
files must also be unchanged between the PR base and head. Native dialogs,
MOTW/SmartScreen behavior, and release publication remain manual.

## Deferred packaged coverage

LUT preview/export parity is not yet part of the packaged E2E. It needs a
deterministic `.cube` fixture and a declared pixel tolerance, and is tracked in
[#267](https://github.com/Magehawks/orga-drone/issues/267). Native folder/open/save
dialogs, 1080p real-media export review, and MOTW/SmartScreen remain manual
release checks. A missing automated journey is a known gap, not a pass;
admission requires the exact journey set.

## What stays manual

These need a Windows desktop, real footage, or a browser-downloaded zip. They
are not part of the journey check:

- The pywebview / WebView2 window, app icon, and bundled fonts are no longer
  completely manual: startup and basic playback are automated. Visual fidelity,
  font rendering, native window behavior, and GPU-specific playback remain human checks.
- Native folder, open, and save dialogs.
- Playback quality, the Story playhead, transitions, overlays, masks, and zoom.
- A library of real drone photos and videos, GPS tracks, and large-library Browse memory.
- A full Studio MP4 of that library with private footage. The packaged E2E uses
  a short synthetic export; watching a real export is still a human check.
- The Mark-of-the-Web zip checklist in `packaging/README.md` (browser download, Explorer extract, relaunch).
- Product behavior that exists only on an unmerged pull-request stack. This smoke follows the app surface on the branch it runs on. It does not click features that branch does not contain.

The check is visible on the pull request. This repo change does not edit branch
protection, so a green check is evidence for the reviewer, and a person still
decides to merge.

Stacked PRs must report their actual base and CI evidence. Normal development
PRs target develop. Packaged Windows E2E and Main admission are triggered for
main-targeted PRs; this policy does not add those workflows to develop PRs.

## Periodic and release review

Review current App journey smoke and relevant packaged evidence. The Product
Owner periodically exercises integrated changes with real media and records bug
issues. At release-candidate stage, complete the packaging/MOTW and realistic
editing/export checks. Synthetic coverage is not proof of visual fidelity or
native-dialog behavior, and CI is not release approval.

## Later slices

Leave these for a follow-up. They are not required to see a failure on a pull request:

- A browser driver against the local server for interactions the packaged E2E
  does not cover.
- Native dialog automation and a MOTW extraction smoke test.
- A longer real-media export fixture for visual review.

## Studio export integrity journey

`test_scan_story_export_real_mp4` extends the HTTP journey with two synthetic
photos (JPEG and PNG), a Studio timeline, resolution options, preparation, and
an asynchronous real FFmpeg export. It decodes the complete MP4 to verify six
seconds and the red/blue clip order, and checks that source bytes are unchanged.
This test skips explicitly when FFmpeg is unavailable. It does not verify
Windows/WebView2, native save dialogs, or visual playback in the packaged app.
