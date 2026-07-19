# Packaging notes

orga-drone is distributed in two ways:

1. **Python application** (this repo) — `pip install -e .` / `requirements.txt`
2. **Precompiled binaries** — GitHub Releases (Windows onefolder via PyInstaller)

## Windows build (PyInstaller)

Requires an editable install so package data resolves correctly:

```powershell
.\.venv\Scripts\activate
pip install -e .
pip install pyinstaller
pyinstaller packaging\orga-drone.spec --noconfirm --clean --distpath dist
```

Output: `dist/orga-drone/` (exe + `_internal` deps, including `templates` / `static` / `locales`).

Release layout (local, not committed as binaries):

```text
releases/1.1.0/orga-drone/          # copy of dist/orga-drone
releases/1.1.0/orga-drone-windows-x64.zip
releases/1.1.0/README.md            # points to the GitHub Release
```

User data stays outside the binary (`%APPDATA%/orga-drone`). Do not embed library paths, `.env`, or media in artifacts.

## CI idea

On git tags, GitHub Actions can build Windows (then macOS/Linux) artifacts and attach them to a Release. No secrets are required for a basic public build.
