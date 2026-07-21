# Packaging notes

orga-drone is distributed in two ways:

1. **Python application** (this repo) — `pip install -e .` / `requirements.txt`
2. **Precompiled binaries** — GitHub Releases (Windows **onefolder** via PyInstaller)

## End-user experience (Windows)

**Double-click `orga-drone.exe`** → a native desktop window opens (pywebview + Edge WebView2).
No system browser is launched. Closing the window stops the local server.

If WebView2 / pywebview cannot start, the app falls back to the system browser.
Force browser mode with `ORGA_DRONE_BROWSER=1`.

First launch with an empty library opens the **Library** page so “Add folder” is obvious.

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

Output: `dist/orga-drone/` (exe + `_internal` deps, including `templates` / `static` / `locales`).

The exe is built with `console=False` (no black console window). For debugging a build,
temporarily set `console=True` in `orga-drone.spec`.

Release layout (local, not committed as binaries):

```text
releases/1.2.0/orga-drone/          # copy of dist/orga-drone
releases/1.2.0/orga-drone-windows-x64.zip
releases/1.2.0/README.md            # points to the GitHub Release
```

**Note:** Existing GitHub Release zips (before the desktop-shell change) still open the
system browser. Rebuild and publish a new release so end users get double-click → window.

User data stays outside the binary (`%APPDATA%/orga-drone`). Do not embed library paths, `.env`, or media in artifacts.

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

## CI idea

On git tags, GitHub Actions can build Windows (then macOS/Linux) artifacts and attach them to a Release. No secrets are required for a basic public build.
