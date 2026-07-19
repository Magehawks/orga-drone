# Packaging notes

orga-drone is distributed in two ways:

1. **Python application** (primary today) — `pip install -e .` / `requirements.txt`
2. **Precompiled binaries** (planned) — GitHub Releases for users without Python

## Planned Windows build (PyInstaller)

Example once packaging is wired:

```bash
pip install pyinstaller
pyinstaller --name orga-drone --onefile -m orga_drone
```

A future `orga-drone.spec` should bundle:

- `orga_drone/templates`
- `orga_drone/static`
- `orga_drone/locales`

User data must remain outside the binary (`%APPDATA%/orga-drone`).

## CI idea

On git tags, GitHub Actions can build Windows (then macOS/Linux) artifacts and attach them to a Release. No secrets are required for a basic public build.

Do not embed personal library paths, `.env` files, or media in release artifacts.
