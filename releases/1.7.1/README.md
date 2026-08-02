# orga-drone 1.7.1

Prebuilt Windows binaries are **not** stored in git.

Download the release assets from:

**https://github.com/Magehawks/orga-drone/releases/tag/v1.7.1**

Artifact: `orga-drone-windows-x64.zip` (onefolder build: `orga-drone.exe` + dependencies).

## Fixed

- Browse paginates the media grid (default 48 per page) and unloads off-screen
  thumbnails so WebView2 / Edge memory stays bounded on large libraries
- Returning from media detail restores Browse filters and scroll position; Back
  to browse is a clearer primary control with Referer fallback when needed

## Changed

- `.gitignore` keeps shared `.cursor/agents` and `.cursor/rules` (and `.github`)
  tracked while ignoring other local Cursor state

If video browsing feels heavy under Windows Defender, exclude the unzipped
`orga-drone` folder (see `packaging/README.md`).
