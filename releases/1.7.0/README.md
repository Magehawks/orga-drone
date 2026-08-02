# orga-drone 1.7.0

Prebuilt Windows binaries are **not** stored in git.

Download the release assets from:

**https://github.com/Magehawks/orga-drone/releases/tag/v1.7.0**

Artifact: `orga-drone-windows-x64.zip` (onefolder build: `orga-drone.exe` + dependencies).

## Added

- Native folder picker for library roots (desktop shell via pywebview)
- GitHub Actions CI (Ruff, MyPy, pytest) on pull requests

## Changed

- Manual path entry remains available; browser-only mode keeps a graceful fallback

If video browsing feels heavy under Windows Defender, exclude the unzipped
`orga-drone` folder (see `packaging/README.md`).
