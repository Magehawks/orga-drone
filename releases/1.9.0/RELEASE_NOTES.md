Local-first drone media library with a Studio memory-editor UI. This release
adds Browse controls for larger libraries and unlocks Studio MP4 export for
photo-only stories.

It is not a professional video editor, and it does not upload to social networks.

## Why 1.9.0

1.8.1 would fit a fixes-only release. Since 1.8.0 the app also ships new
behavior: Browse page size, bulk add of the current page to Studio, the
version in the UI, and MP4 export when a Story contains only photos (720p or
1080p). Those are backward-compatible features, so this is **1.9.0**.

## Highlights

- **Browse page size** — 50, 100, or 200 items per page
- **Add page to Studio** — add the current Browse page to the open Studio project
- **Photo-only export** — a Story with photos (and no video) can export an MP4
  at 720p or 1080p; each photo uses the existing still duration
- **Version in the UI** — the running application version is shown in the interface
- **Browse stays put** — adding an item to Studio keeps the current page
- **Studio browser scroll** — the media browser scrolls inside the Studio layout
- **Quiet export** — FFmpeg no longer opens a console window on Windows
- **Live Photos** — same-stem HEIC/JPG + MOV stays a photo; still-picture MOVs
  are not treated as video

Studio projects, Story canvas, Title Cards, transitions, soundtrack playlist,
and Open video / Show in folder from 1.8.0 remain.

## Windows packaging (1.9.0)

Same desktop shell as 1.8.0: pywebview + WebView2, bundled ffmpeg, local fonts,
and the Orga Drone icon. Downloaded zips still relocate pythonnet and WebView2
when Mark-of-the-Web blocks LoadFrom.

SHA256 (`orga-drone-windows-x64.zip`):
`PENDING`

Built from `main` at `PENDING`.

## Upgrade notes

- Opening 1.9.0 uses the existing SQLite index in `%APPDATA%\orga-drone\`.
  Media files on disk are not modified.
- A library from **v1.8.0** opens as before. No new migration is required for
  this release.
- SQLite upgrades remain forward-only.

## Windows

Download `orga-drone-windows-x64.zip`, unzip, and double-click `orga-drone.exe`.
Requires Edge WebView2 Runtime (usually preinstalled on Windows 10/11).

This zip includes the application and a bundled ffmpeg (via imageio-ffmpeg)
for thumbnails, flow merge, and Studio export. You do not need ffmpeg on PATH.
Source media and your database are never packed into the zip.

If video browsing feels heavy under Windows Defender, exclude the unzipped
`orga-drone` folder (see `packaging/README.md`).

## Known limitations

- Full library rescan per root (not incremental)
- Flight sessions and duplicates are heuristics
- Ask the library is rule-based (not an LLM)
- Export cannot be cancelled mid-render
- Photo-only export offers 720p and 1080p (no 4K upscale)
- Soundtrack loop is single-song only; no audio crossfades, ducking, or
  waveforms
- Social share destinations, Library albums, plugins, and CI-built installers
  are not included
- macOS/Linux remain Python (`python -m orga_drone`); this asset is Windows x64
