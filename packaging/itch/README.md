# itch.io Windows test channel

Repeatable process for uploading the existing **Windows x64 PyInstaller
onefolder** to a **Draft or Restricted** itch.io project with butler. This is
not an in-app updater, not a public paid launch, and not a replacement for the
Windows smoke test.

`python packaging/itch_channel.py` only prints a command. It does not run
butler and does not upload.

## What is already decided

| Slot | userversion | Identity | Upload from this tree? |
|------|-------------|----------|------------------------|
| A | `1.9.0` | GitHub Release baseline, commit `9eb28b0`, zip SHA256 in `releases/1.9.0/RELEASE_NOTES.md` | No. Use that release zip, not a rebuild of current `main`. |
| B | `1.10.0` | Next feature build: image correction **and** timed overlays | No. Timed overlays (issue #78) are not in this tree, and `__version__` is still `1.9.0`. |

Current `main` contains image correction and still reports version `1.9.0`.
Do not push it as Version A (it is not commit `9eb28b0`) or as Version B
(overlays are absent and the userversion would collide with A).

Test channel name: `windows-x64-test`. The name contains `windows`, so butler
tags it as a Windows executable. Do not use a production channel for this test.

## Gates that stay in force

1. **Manual MOTW smoke test** in [`packaging/README.md`](../README.md). A green
   `dist\orga-drone` run is not enough. Record the zip SHA256, commit, and
   date before any upload.
2. **ADR 0031** (manual Windows build) is an extra gate. The build workflow
   produces a non-publishing Actions artifact only; it does not create a GitHub
   Release. It does not replace the smoke test and must not be bypassed.
3. **Page visibility** is Draft or Restricted. If you cannot keep the project
   off public browse and search, stop. Do not upload the test build to a
   public page.
4. No CI workflow in this repo runs butler.

## One-time project setup

1. Create an itch.io project for the convenience build. Leave pricing and
   public release unset.
2. Set **Visibility & access** to **Draft** or **Restricted**. Restricted plus
   a download key is the setup that lets a test machine install through the
   itch.io desktop app without listing the page publicly.
3. Install butler and `butler login` as the project owner. Keep the API key
   out of the git repo.

## Version A

1. Download the published `orga-drone-windows-x64.zip` for 1.9.0 (the asset
   whose SHA256 is in the 1.9.0 release notes).
2. Check it:

```powershell
python packaging\itch_channel.py verify-zip .\orga-drone-windows-x64.zip
```

3. Run the mandatory smoke test on a **browser-downloaded** copy of that zip
   (Explorer extract, parentheses path). Do not push that MOTW-stamped extract.
4. Extract a clean copy of the same zip and check the onefolder that directly
   contains `orga-drone.exe` and `_internal`:

```powershell
python packaging\itch_channel.py check-layout .\orga-drone
```

5. Print the first push. `--hidden` is required because a new channel is
   public on the page by default. `--hidden` only works while the channel is
   being created.

```powershell
python packaging\itch_channel.py command --slot A --build .\orga-drone --zip .\orga-drone-windows-x64.zip --target owner/game --visibility restricted
```

Replace `owner/game` with the lowercase itch.io slug. The tool refuses
`public`, a mismatched SHA256, user data inside the folder, and a missing
`_internal` directory.

6. Read the printed command. Confirm the dashboard is still Draft or
   Restricted. Run the butler command yourself.
7. On the Edit game page, confirm the new channel is hidden and the page is
   still not Public. Unhide `windows-x64-test` only after that check. If the
   page is Public, do not unhide it.

As soon as a non-hidden push finishes, the itch.io app can update players who
already installed that channel. Hidden avoids offering the file while you
check visibility. There is no butler flag that sets page visibility; the
dashboard does.

## Install A and prepare user data

On a clean Windows test PC, install **A through the itch.io desktop app**
(not by unzipping). Then:

- Add a library folder. Remember that folder: original media must stay there
  untouched.
- Create a Studio project (title, clip order). Quit and relaunch to confirm
  it was stored.
- Copy `%APPDATA%\orga-drone\orga-drone.sqlite3` somewhere outside both the
  itch install folder and `%APPDATA%\orga-drone`.

The install directory belongs to the itch.io app. The database, theme,
`app_prefs.json`, thumbnails, and the pythonnet/WebView2 caches live under
`%APPDATA%\orga-drone`.

## Version B

Do not run a B push from this commit. `python packaging/itch_channel.py status`
lists the blockers.

Build B only from a commit that:

- sets `__version__` to `1.10.0`
- contains image correction (`src/orga_drone/studio_image.py`)
- contains timed overlays, and only then adds the marker file
  `packaging/itch/OVERLAYS_READY`
- has passed the same MOTW smoke test

Push B to the **same** channel so the itch.io app treats it as an update.
Do not pass `--hidden` on that second push: butler rejects `--hidden` once
the channel exists, and omitting `--channel-exists` makes this tool refuse
so it does not create a brand-new visible channel.

```powershell
python packaging\itch_channel.py command --slot B --build .\orga-drone --target owner/game --visibility restricted --channel-exists
```

Userversion `1.10.0` is a label. itch.io orders builds by upload order, not
by semver.

## What to verify after the app applies B

The itch.io app should download the update without you replacing files by
hand. Then check:

- Native window, folder picker, soundtrack picker, MP4 save dialog
- The library roots still point at the same media, and those files are unchanged
- The Studio project from A is still there
- Image correction and timed overlays persist and appear in preview and in an MP4 export
- Theme and last export directory are still present

Record the result in [`AB_TEST_RECORD.md`](AB_TEST_RECORD.md). A blank or
NOT RUN record means the public page stays unpublished.

## ZIP downloads do not auto-update

| How the user got the app | Updates |
|--------------------------|---------|
| itch.io desktop app, this Windows channel | The app looks for a newer build on startup and about every 30 minutes. One Windows candidate updates in place. |
| ZIP from the itch.io website, GitHub Releases, or any other file copy | No. The itch.io app does not track that folder. The user installs the new zip themselves. |

Pushing a new build still replaces the file offered to **new** website
downloads. People who already unzipped an older zip are not notified and not
patched.

User data does not move with either path. Replacing the application folder
leaves `%APPDATA%\orga-drone` and the library folders alone. The local
stand-in for that split is `replace_install_directory` in
`packaging/itch_channel.py` (tests only; it is not an updater).

## Interrupted update and rollback

- Do not delete `%APPDATA%\orga-drone` to recover. That directory holds the
  library and Studio projects.
- Do not delete or replace files in the library folders. The app does not
  write exports back into source media as part of an update.
- If the itch.io app stops mid-update, open the app and reinstall or check
  for updates on that library entry. That replaces the install folder only.
- To put the channel back on A, smoke-test is already done for that zip;
  push the extracted A onefolder to `windows-x64-test` again. The latest
  upload becomes the build clients receive, even if its userversion is lower.
- If B's build migrated SQLite, launching A against the migrated database can
  fail (upgrades are forward-only). Restore the copied `orga-drone.sqlite3`
  before launching A. Image correction on current `main` stores sliders in
  the existing `effect_settings` JSON and does not by itself add a table.
  Timed overlays are not in this tree, so treat their migration as unknown
  until that build exists.
- `pythonnet-home` and `webview-lib` under app data are caches. They may be
  recreated. They are not the library.

## Page text

Paste [`PAGE.md`](PAGE.md) into the itch.io description when the page is
created. Keep the project Draft or Restricted until the A→B record and the
smoke test both pass.

## Commands

```powershell
python packaging\itch_channel.py status
```
