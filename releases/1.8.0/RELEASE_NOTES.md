Local-first drone media library with a Studio memory-editor UI. This release
completes the first Create → Share slice on Windows desktop: arrange a story,
optionally add music, export an MP4, and open or reveal the file.

It is not a professional video editor, and it does not upload to social networks.

## Highlights

- **Studio projects** — multiple local edit projects (`studio_projects` /
  `studio_clips`); Projects switcher; last-opened restore; Clear Studio empties
  the Story only
- **Story editing** — order, estimated runtime, video Cut (source in/out),
  Title Cards, Cut / Fade through black / Crossfade
- **Preview** — synced playhead, time-based Story canvas (Fit to story / zoom),
  labeled transitions, Inspector headings that distinguish selection from the
  playhead-active clip
- **Soundtrack** — optional sequential playlist of up to 8 local songs in
  preview and MP4 export; loop still applies only when there is one song;
  read-only time-proportional coverage on the Story canvas; tiles use the same
  px/s mapping as Story items
- **Export** — local MP4 with configurable resolution (up to source max);
  after success, Open video / Show in folder on Windows

Library, browse, map, Ask the library, and scan behavior from 1.7.x remain.

## Windows packaging (1.8.0)

The Windows zip keeps a **native desktop window** (pywebview + WebView2) when
unzipped from a browser download or into paths with parentheses (e.g.
`orga-drone-windows-x64(2)`). Native folder, soundtrack, and export pickers
work; UI fonts and the app icon are bundled locally (no Google Fonts request).

Fixes since the first 1.8.0 upload:

- Relocate the full **pythonnet** package when LoadFrom is blocked
- Copy **WebView2** assemblies to `%APPDATA%\orga-drone\webview-lib\` when
  Mark-of-the-Web blocks `Microsoft.Web.WebView2.Core.dll`
- Embed the Orga Drone rotor **icon** in the Windows exe and static assets

SHA256 (`orga-drone-windows-x64.zip`):
`7B48CD9A557E3C2262AED2D57A199A3C74AEA964917EF3A9B3597C6F74F707FC`

Built from `master` at `32d3948`.

## Upgrade notes

- Opening 1.8.0 migrates the existing SQLite index in
  `%APPDATA%\orga-drone\` (additive tables/columns). Media files on disk are
  not modified.
- A library from **v1.7.1** opens as before. Studio starts empty until you
  create a project.
- SQLite upgrades are forward-only. Keep a copy of `orga-drone.sqlite3` if you
  might reinstall 1.7.1.
- If you ran development builds between 1.7.1 and 1.8.0: one-song soundtracks
  keep working; the unique one-song index is dropped so playlists can grow.

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
- Soundtrack loop is single-song only; no audio crossfades, ducking, or
  waveforms
- Social share destinations, Library albums, plugins, and CI-built installers
  are not included
- macOS/Linux remain Python (`python -m orga_drone`); this asset is Windows x64
