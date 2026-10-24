# Pull request end-to-end checks

How a pull request shows an automated pass through the local app, and which
checks stay with a person.

Orga Drone is a local FastAPI app with an optional pywebview (WebView2) window.
Media stays on disk. CI has no access to a reviewer’s library and no desktop
session on the Ubuntu pull-request runner.

## What already runs on every pull request

The **CI** workflow (`.github/workflows/ci.yml`) runs on `pull_request`:

| Check | What it does |
| --- | --- |
| **Ruff, MyPy and unit tests** | `ruff check .`, `mypy src`, then `pytest` for unit and route tests. This step skips `tests/test_pr_journey_smoke.py` so a journey failure is reported by the check below. |
| **App journey smoke** | `pytest tests/test_pr_journey_smoke.py` |

A local `pytest` from the repo root runs the unit tests **and** the journey
file. Install dev tools with `pip install -e ".[dev]"`.

The **Windows release** workflow does not run on pull requests. It calls this
CI workflow and builds a zip only after both checks pass. Publishing that zip
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

## What stays manual

These need a Windows desktop, real footage, or a browser-downloaded zip. They
are not part of the journey check:

- The pywebview / WebView2 window, app icon, and bundled fonts (no system-browser fallback).
- Native folder, open, and save dialogs.
- Playback, the Story playhead, and how transitions, adjustments, overlays, masks, or zoom look.
- A library of real drone photos and videos, GPS tracks, and large-library Browse memory.
- A full Studio MP4 of that library. Encoder pieces already have pytest coverage, including photo-only export; watching an export of private media is still a human check.
- The Mark-of-the-Web zip checklist in `packaging/README.md` (browser download, Explorer extract, relaunch).
- Product behavior that exists only on an unmerged pull-request stack. This smoke follows the app surface on the branch it runs on. It does not click features that branch does not contain.

The check is visible on the pull request. This repo change does not edit branch
protection, so a green check is evidence for the reviewer, and a person still
decides to merge.

Stacked pull requests use their own base branch. They pick up this workflow
when that base contains `.github/workflows/ci.yml` from `main` (after this
change is merged, and after the stack includes that `main`). Until then, read
the journey result on the pull request that added it, and keep the desktop pass
on the product pull requests.

## Tonight’s review pass

1. On the journey-smoke pull request, open **Checks** and read **App journey smoke** (the summary at the top of the job, then the pytest log if it is red).
2. Walk the product pull requests in the desktop app with real media. A green journey check does not cover WebView2, native dialogs, or unmerged Studio behavior.
3. Keep the Mark-of-the-Web checklist for any zip you might publish. CI building or testing the app is not that checklist.

## Later slices

Leave these for a follow-up. They are not required to see a failure on a pull request:

- A browser driver (for example Playwright) against the local server, for clicks the `TestClient` never makes.
- A Windows job that launches the unpackaged app. WebView2 still needs a person for the native dialogs and for the Mark-of-the-Web zip.
