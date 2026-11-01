# Packaging notes

orga-drone is distributed in two ways:

1. **Python application** (this repo) — `pip install -e .` / `requirements.txt`
2. **Precompiled Windows onefolder** — built with PyInstaller for itch.io / local
   maintainer use. The zip is **not** attached to GitHub Releases (notes/tag only).

## End-user experience (Windows)

**Double-click `orga-drone.exe`** → a native desktop window opens (pywebview + Edge WebView2).
No system browser is launched. Closing the window stops the local server.

If WebView2 / pywebview cannot start, the packaged app shows an error dialog and
writes `orga-drone.log` plus `startup-crash.log`. It does **not** open the system
browser (native folder / soundtrack / export dialogs need the desktop window).
Force browser mode only with `ORGA_DRONE_BROWSER=1`.

First launch with an empty library opens **Home**. The hero is the Orga Drone
logo, and **Add media** starts the existing folder import.

## Windows build (PyInstaller)

**Always use onefolder** (`COLLECT` in `orga-drone.spec`). Do **not** switch to onefile:
onefile extracts the whole bundle to a temp dir on every launch, which is painful for a
local media app (extra IO + antivirus scans).

Requires an editable install so package data resolves correctly:

```powershell
.\.venv\Scripts\activate
pip install -e .
pip install pyinstaller
pyinstaller packaging\orga-drone.spec --noconfirm --clean --distpath dist
```

The spec bundles `pywebview` (`collect_all("webview")`). On Windows, **Edge WebView2
Runtime** must be present (preinstalled on current Windows 10/11; otherwise install the
[Evergreen Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)).

Output: `dist/orga-drone/` (exe + `_internal` deps, including `templates` /
`static` / `locales`, and the bundled **ffmpeg** binary from `imageio-ffmpeg`).

Studio MP4 export, video thumbnails, and flow merge use that bundled ffmpeg.
End users of the Windows zip do **not** need ffmpeg on PATH. `find_ffmpeg()`
still prefers a system ffmpeg if one is present, then falls back to the
bundled binary. imageio-ffmpeg typically ships ffmpeg only (no ffprobe);
export already falls back to `ffmpeg -i` when ffprobe is absent.

Before the zip is uploaded, `packaging/windows_third_party.py` runs the
bundled ffmpeg, copies the notices it can actually read, and writes
`THIRD_PARTY_NOTICES/ITCH_SALE_VERDICT.txt`. `verify-zip` exits 0 when that
verdict is GO and exits 2 when it is NO-GO. The workflow stops before the
upload on any non-zero exit. When
`packaging/third_party/ffmpeg-gpl/bin/ffmpeg.exe` is present, the workflow
copies it over the imageio-ffmpeg binary. Without that file the wheel binary
stays in the zip and the verdict stays NO-GO. The evidence is in
`packaging/WINDOWS_THIRD_PARTY.md`. That file is not a compliance certificate.
The project license stays MIT.

The exe is built with `console=False` (no black console window). For debugging a build,
temporarily set `console=True` in `orga-drone.spec`.

The Windows EXE icon is `packaging/assets/orga-drone.ico` (16–256px). The same
artwork is served as `/static/icons/orga-drone.png` (favicon) and
`/static/icons/orga-drone.ico` (pywebview `start(icon=…)` on Windows).

Release layout (local fallback, not committed as binaries):

```text
releases/<version>/orga-drone/          # copy of dist/orga-drone (gitignored)
releases/<version>/orga-drone-windows-x64.zip
releases/<version>/README.md            # local notes; binaries stay off GitHub Releases
```

The manual GitHub Actions build writes the same zip name and the same
`orga-drone/` + `_internal/` layout as a non-publishing Actions artifact only. See
[Manual Windows build](#manual-windows-build-github-actions). It never creates
or edits a GitHub Release. The local commands above stay available when Actions
cannot be used.

User data stays outside the binary (`%APPDATA%/orga-drone`). Do not embed library paths, `.env`, or media in artifacts.

Offline reverse geocoding (`reverse-geocoder`, for scan auto-tags) uses the dated GeoNames extract beside `orga_drone.geocode` — no network required. Set `ORGA_DRONE_GEOCODE=off` to disable place lookup.

Media files are always streamed from the configured library roots on disk — never from
`sys._MEIPASS`. Only UI assets (templates/static/locales) live in the package.

UPX is **disabled** in the spec: packed binaries trigger more Windows Defender scans
on every file open (video Range requests), which looks like CPU/IO spikes.

### Windows Defender (recommended for smoother playback)

If the packaged app feels slower than `python -m orga_drone` when browsing or seeking
video, exclude the install folder from real-time scanning, for example:

- `C:\Users\<you>\…\orga-drone\` (unzipped release / `dist\orga-drone`)
- optionally your drone library root(s)

Defender often re-scans the frozen exe and every media open; Python from a venv is
usually trusted already. A folder exclusion is the practical mitigation.

Packaged mode sets `ORGA_DRONE_PACKAGED=1` (also detectable via `sys.frozen`) and
disables Uvicorn access logs so Range requests do not flood logs.

The Windows desktop window uses pywebview 6.x + pythonnet 3.x (`clr_loader`).
`pythonnet.load()` always loads `Path(__file__).parent / "runtime" / "Python.Runtime.dll"`
and has no public DLL-path override. .NET Framework cannot LoadFrom that path when it
contains parentheses (Windows “Copy (2)” unzip) and also needs the full `runtime/`
facade set (not just `Python.Runtime.dll`). Downloaded zips may add a
`Zone.Identifier` stream that blocks LoadFrom.

When the installed path is unsafe, **or** a frozen build still has
`Zone.Identifier` on `Python.Runtime.dll`, the packaged app copies the whole
`pythonnet` package to a CLR-safe home (`%APPDATA%\orga-drone\pythonnet-home\`
when that path is safe) without Mark-of-the-Web, then binds that copy with
`importlib.util.spec_from_file_location` so PyInstaller's FrozenImporter does not
keep `pythonnet.__file__` on the unzip path. Stock `import clr` / `pythonnet.load()`
then load the relocated `runtime/` tree.

Windows Explorer also stamps **every** file extracted from a browser-downloaded
zip with `Zone.Identifier` (`ZoneId=3`). `.NET` then refuses
`clr.AddReference` of `_internal/webview/lib/Microsoft.Web.WebView2.Core.dll`
(`HRESULT 0x80131515`). In a frozen build that still has that stream, the app
byte-copies `webview/lib/*.dll` (Core, WinForms, interop, `WebView2Loader`) to
`%APPDATA%\orga-drone\webview-lib\` and patches `webview.util.interop_dll_path`
so LoadFrom uses the local copy. It does **not** enable `loadFromRemoteSources`.
Users are never asked to Unblock files.

If the desktop window still cannot start, the app logs the exception to
`orga-drone.log` and `startup-crash.log` and shows an error dialog; it does
**not** silently open the system browser (native Studio pickers would not work).
Force browser mode only with `ORGA_DRONE_BROWSER=1`.

UI fonts (Outfit, Sora, IBM Plex Mono) are bundled under `static/fonts/` and
served locally. The desktop UI does not load Google Fonts from the network.

## Manual Windows build (GitHub Actions)

Workflow: `.github/workflows/windows-release.yml`.

It runs only when a maintainer starts it with `workflow_dispatch`. Push, pull
request, merge, and tag events do not start it. It never creates or edits a
GitHub Release, never uploads to itch.io, and never posts to Discord. The only
output is a non-publishing Actions artifact kept for 30 days.

It builds the existing onefolder spec (`packaging/orga-drone.spec`,
`packaging/run_orga_drone.py`) on `windows-latest` with Python 3.12 and
**PyInstaller 6.22.3**. It does not switch to onefile, Electron, or Tauri.
FFmpeg (imageio-ffmpeg), templates, static files, and locales are bundled the
same way as a local build. Source media, `.env`, and the user SQLite database
are not part of the app and the workflow fails if they appear in `dist/orga-drone`.

Pull requests run `.github/workflows/ci.yml` (Ruff, MyPy, pytest, and the App
journey smoke in `docs/PR_E2E.md`). The manual Windows build calls that same
workflow and **does not package** if it fails. The journey smoke is a synthetic
library path. It does not replace the Mark-of-the-Web checklist below.

### When it runs

| Trigger | Result |
| --- | --- |
| Actions → **Manual Windows build** → **Run workflow** (`workflow_dispatch`) | Zip as a non-publishing Actions artifact only. No GitHub Release. |
| Push, pull request, merge, or `vX.Y.Z` tag | Nothing. These events do not start the workflow and cannot publish. |

A maintainer starts the build from a commit on `main`. `packaging/verify_release_version.py`
is the gate: `pyproject.toml` `project.version` must be `X.Y.Z` and
`src/orga_drone/__init__.py` `__version__` must be the same string. A missing
version or a non-semver version fails the job before packaging. A manual run on
a tag also checks that the tag is exactly `v{version}`.

Each run prints `version=` and `commit=` in the logs and the job summary.
The package job also prints `sha256=`.

### Version procedure

1. Set the same `X.Y.Z` version in `pyproject.toml` (`project.version`) and
   `src/orga_drone/__init__.py` (`__version__`).
2. Merge that change to `main`.
3. Start the **Manual Windows build** workflow from that commit.

A `vX.Y.Z` tag is an optional historical marker. It does not start a build,
create a release, or publish anything. If the maintainer creates one, it must
match the version on that commit (version `1.9.0` → tag `v1.9.0`). Tag
protection is a repository setting; see `docs/RELEASE_SECURITY.md`.

### Artifacts

| Name | Where | What it is |
| --- | --- | --- |
| `orga-drone-windows-x64.zip` | Actions artifact and/or local `releases/<version>/` | Zip whose top folder is `orga-drone/` (`orga-drone.exe` + `_internal/`). **Not** a GitHub Release asset. |
| `orga-drone-windows-x64.zip.sha256` | Same places | SHA256 of that zip (`sha256sum -c` format) |
| Actions artifact `orga-drone-windows-x64` | The workflow run, kept 30 days | Those files plus `release-build.txt` (`version`, `commit`, `sha256`) |

GitHub wraps an Actions artifact in an outer zip when you download it from the
browser. The **inner** file `orga-drone-windows-x64.zip` is the candidate.
Prefer that Actions download or a local `releases/<version>/` build for the
MOTW smoke test. Do **not** upload the zip to the GitHub Release.

### Checksum

```powershell
Get-FileHash -Algorithm SHA256 .\orga-drone-windows-x64.zip
```

Compare the hash to `orga-drone-windows-x64.zip.sha256` and to the release notes,
if a manual release is created. On Linux or macOS:
`sha256sum -c orga-drone-windows-x64.zip.sha256`.

### Obtain a candidate (not on the GitHub Release)

Windows zips are never attached to GitHub Releases. Maintainer candidates come
from the Actions artifact or a local `releases/<version>/` build.

1. Preferred for the MOTW gate: download the Actions artifact
   `orga-drone-windows-x64` in the browser while signed in. Extract the outer
   zip with Windows Explorer (Mark-of-the-Web propagates), then smoke-test the
   inner `orga-drone-windows-x64.zip`. Do **not** use `gh run download`,
   `curl`, or a copy from `dist/` for the MOTW path (those skip MOTW) unless
   you apply an equivalent `Zone.Identifier` stream.
2. Local fallback: build into `releases/<version>/` with the PyInstaller
   commands above. A manual notes-only GitHub Release still requires the human
   release gate below.

### Manual release (human only)

The workflow does **not** create a GitHub Release. If the maintainer decides to
publish one, create a **notes-only** draft by hand in the GitHub UI (or with a
manual `gh release create vX.Y.Z --draft`). Never upload the Windows zip.

After the smoke test passes, edit the draft notes so they include the tested
ZIP SHA256, git commit, test date, and outcome, then press **Publish release**.
That human step is the publication gate. Do not publish on failure. Only a
repository maintainer with write access may publish; see
[`docs/RELEASE_SECURITY.md`](../docs/RELEASE_SECURITY.md).

### Recovery

| Situation | What to do |
| --- | --- |
| Version mismatch | Fix `pyproject.toml` and `__version__`, merge, and start the manual build again. The failed run did not create a release. |
| Smoke test failed | Leave any manual draft unpublished and delete it if one was created. A failed candidate is never published. |
| Need a new candidate for the same release | Re-run the **Manual Windows build** workflow. It replaces the Actions artifact and never touches a release. Update the SHA256 in the notes before publishing. |
| Published by mistake | `gh release edit vX.Y.Z --draft` returns the release to a draft (it leaves the public release list). If GitHub rejects that edit, `gh release delete vX.Y.Z --yes` removes the release and its assets. Prefer a new patch tag for a real fix if anyone may already have downloaded the zip. |
| Actions unavailable | Use the local PyInstaller commands in [Windows build (PyInstaller)](#windows-build-pyinstaller). Do not commit `dist/` or the zip. |

No code-signing, installer, or self-updater is involved. macOS and Linux are
still the Python application only.

## Windows pre-release smoke test (mandatory)

Every Windows release **must** pass this checklist before a maintainer
**publishes** it. Building a candidate is not publication. A green smoke test
from `dist\orga-drone\` alone is **not sufficient** — that path never carries
Mark-of-the-Web (MOTW).

Record the zip SHA256, git commit, test date, and outcome in the manual release
notes before publishing. Do not publish if any step fails.

### Why MOTW matters

When users download the zip from GitHub in a browser, Windows adds an NTFS
`Zone.Identifier` alternate data stream (Mark-of-the-Web, `ZoneId=3`). Extracting
with **Windows Explorer** copies that stamp onto every extracted file. .NET
`Assembly.LoadFrom` then refuses pywebview's bundled WebView2 assemblies
(`HRESULT 0x80131515`) unless the app relocates them — behaviour covered in the
notes above. Each release must re-verify that path.

### Checklist

#### 1. Obtain the candidate zip

Preferred: start the [Manual Windows build](#manual-windows-build-github-actions)
(`workflow_dispatch`) and download `orga-drone-windows-x64.zip` as described
there. You should not need to rebuild the exe locally. Tag pushes do not start
this build.

Fallback: follow [Windows build (PyInstaller)](#windows-build-pyinstaller)
above and package `dist/orga-drone` as `orga-drone-windows-x64.zip`.

#### 2. Obtain a MOTW-marked zip (**mandatory**)

The zip used for smoke testing **must** carry Mark-of-the-Web before extract.

- **Preferred:** Download the Actions artifact `orga-drone-windows-x64` in a
  browser (Edge or Chrome, signed in), then use the inner zip. Do **not** use
  `curl`, `gh run download`, or a direct copy from `dist/` for MOTW — those
  paths skip MOTW unless you add an equivalent stream.
- **Acceptable dev equivalent:** Apply MOTW to the locally built zip the same
  way a browser download would (for example by copying a `Zone.Identifier`
  stream onto the zip file).

Confirm MOTW on the zip **before** extract:

```powershell
Get-Content -Path "$env:USERPROFILE\Downloads\orga-drone-windows-x64.zip" -Stream Zone.Identifier
```

Expected: `[ZoneTransfer]` with `ZoneId=3`.

#### 3. Extract with Windows Explorer (**mandatory**)

- Delete any previous test folder.
- Right-click the MOTW-marked zip → **Extract All…** (not 7-Zip, WinRAR, or
  `Expand-Archive` for this step).
- Extract into a path that includes parentheses, for example
  `C:\temp\orga-drone-windows-x64(2)\`.
- Spot-check that extracted files still carry MOTW, for example:

```powershell
Get-Content -Path "C:\temp\orga-drone-windows-x64(2)\orga-drone\orga-drone.exe" -Stream Zone.Identifier
```

#### 4. Functional smoke checks (**mandatory**)

Launch `orga-drone.exe` from the extracted folder and verify:

- [ ] Native desktop window opens (WinForms / pywebview); **no** system-browser
  fallback. `%APPDATA%\orga-drone\startup-crash.log` must **not** appear.
- [ ] App icon and bundled fonts load locally (no Google Fonts network fetch).
- [ ] **Library:** native folder picker opens (Add folder).
- [ ] **Studio:** native open picker for a soundtrack file works.
- [ ] **Studio:** native Save dialog for MP4 export works.
- [ ] A small **1080p** Studio export completes successfully.
- [ ] Close and relaunch — the open Studio project and soundtrack playlist are
  preserved.

Do **not** publish a release if any step fails. A failed candidate stays local
or is deleted; it is not made public.

## itch.io test channel

Publishing that zip to itch.io does **not** replace this smoke test. The
repeatable butler process, Draft/Restricted guard, A/B version ids, and
rollback notes are in [`packaging/itch/README.md`](itch/README.md). The helper
`python packaging/itch_channel.py` prints a command and does not upload.

There is no in-app updater. Copies installed from a ZIP do not receive
itch.io desktop-app updates. User data stays in `%APPDATA%\orga-drone`.

No workflow runs butler, uploads to itch.io, creates a GitHub Release, or posts
a release notification. Publishing to itch.io is a manual maintainer step on the
maintainer's machine. The release automation limits are documented in
[`docs/RELEASE_SECURITY.md`](../docs/RELEASE_SECURITY.md).
