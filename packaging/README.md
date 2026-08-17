# Packaging notes

orga-drone is distributed in two ways:

1. **Python application** (this repo) — `pip install -e .` / `requirements.txt`
2. **Precompiled binaries** — GitHub Releases (Windows **onefolder** via PyInstaller)

## End-user experience (Windows)

**Double-click `orga-drone.exe`** → a native desktop window opens (pywebview + Edge WebView2).
No system browser is launched. Closing the window stops the local server.

If WebView2 / pywebview cannot start, the packaged app shows an error dialog and
writes `orga-drone.log` plus `startup-crash.log`. It does **not** open the system
browser (native folder / soundtrack / export dialogs need the desktop window).
Force browser mode only with `ORGA_DRONE_BROWSER=1`.

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

Output: `dist/orga-drone/` (exe + `_internal` deps, including `templates` /
`static` / `locales`, and the bundled **ffmpeg** binary from `imageio-ffmpeg`).

Studio MP4 export, video thumbnails, and flow merge use that bundled ffmpeg.
End users of the Windows zip do **not** need ffmpeg on PATH. `find_ffmpeg()`
still prefers a system ffmpeg if one is present, then falls back to the
bundled binary. imageio-ffmpeg typically ships ffmpeg only (no ffprobe);
export already falls back to `ffmpeg -i` when ffprobe is absent.

The exe is built with `console=False` (no black console window). For debugging a build,
temporarily set `console=True` in `orga-drone.spec`.

The Windows EXE icon is `packaging/assets/orga-drone.ico` (16–256px). The same
artwork is served as `/static/icons/orga-drone.png` (favicon) and
`/static/icons/orga-drone.ico` (pywebview `start(icon=…)` on Windows).

Release layout (local, not committed as binaries):

```text
releases/1.8.0/orga-drone/          # copy of dist/orga-drone (gitignored)
releases/1.8.0/orga-drone-windows-x64.zip
releases/1.8.0/README.md            # points to the GitHub Release
```

**Note:** Existing GitHub Release zips (before the desktop-shell change) still open the
system browser. Rebuild and publish a new release so end users get double-click → window.

User data stays outside the binary (`%APPDATA%/orga-drone`). Do not embed library paths, `.env`, or media in artifacts.

Offline reverse geocoding (`reverse-geocoder`, for scan auto-tags) is bundled — no network required. Set `ORGA_DRONE_GEOCODE=off` to disable place lookup.

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

## CI idea

On git tags, GitHub Actions can build Windows (then macOS/Linux) artifacts and attach them to a Release. No secrets are required for a basic public build.
