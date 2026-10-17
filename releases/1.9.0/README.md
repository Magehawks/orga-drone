# orga-drone 1.9.0

Prebuilt Windows binaries are **not** stored in git.

Download the release assets from:

**https://github.com/Magehawks/orga-drone/releases/tag/v1.9.0**

Artifact: `orga-drone-windows-x64.zip` (onefolder build: `orga-drone.exe` + `_internal`, including bundled ffmpeg).

Local-first drone media library with a Studio memory-editor UI. This release
adds Browse page size (50/100/200), bulk add of the current page to Studio,
and MP4 export for photo-only stories at 720p or 1080p.

It is not a professional video editor, and it does not upload to social networks.

## Highlights

- **Browse page size** — 50, 100, or 200 items per page
- **Add page to Studio** — add the current Browse page to the open Studio project
- **Photo-only export** — a Story with photos (and no video) can export an MP4
  at 720p or 1080p
- **Version in the UI** — the running application version is shown in the interface
- Fixes: Browse page is kept after Add to Studio; Studio media browser scrolls
  in its own pane; FFmpeg export has no console window; Live Photo / still MOV
  classification

Studio projects, Story canvas, Title Cards, transitions, soundtrack playlist,
and Open video / Show in folder from 1.8.0 remain.

## Upgrade notes

- Opening 1.9.0 uses the existing SQLite index in `%APPDATA%\orga-drone\`.
  Media files on disk are not modified.
- A library from **v1.8.0** opens as before.

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
