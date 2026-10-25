# orga-drone 2.0.0

Local-first drone media library with a Studio memory-editor UI.

This GitHub Release marks the **2.0.0** source and version on `main`. **No Windows executable or zip is attached.** Install from source (`pip install -e .` / `python -m orga_drone`) or keep using an existing packaged build. A later Windows onefolder zip can still be produced from this tag if needed.

It is not a professional video editor, and it does not upload or post to social networks.

## Why 2.0.0

Since 1.9.0 the app grew a complete Studio storytelling slice: overlays, privacy masks, zoom and pan, slow motion, section repeat, image grade, a saturation ramp, telemetry HUD, a flight map, library albums, a Browse timeline, safer local export, and one-file export from the detail page. That is a new product chapter, so this is **2.0.0**.

## Highlights

### Library and Browse

- **Library albums** — named local collections; one file can belong to several albums; references survive a rescan and stay listed when a file is offline
- **Offline catalog** — if a source folder cannot be listed, catalog entries stay and the UI marks them offline
- **Faster rescan** — unchanged files (same size and mtime) skip metadata extraction
- **Browse Timeline** — year / month / day by recording date; missing dates are grouped as Date unknown (not the Studio story timeline)
- **Optional update notice** — off by default; can report a newer published Windows release and link to it; it does not download or install

### Studio

- **Timed overlays** — text, shape, and image (up to 8 per photo or video clip); Fade in, Fade out, Slide in
- **Privacy masks** — rectangular blur or pixelate (up to 8 per clip, fixed for the whole clip); under zoom and pan, preview and MP4 cover the same picture
- **Zoom and pan** — 1×–3×, optional start/end motion
- **Image adjustment** — brightness, contrast, saturation, warmth on photos and videos
- **Saturation ramp** — linear fade from the current grade toward black and white on a video clip
- **Slow motion** — 0.5× or 0.25× on a selected video section (source audio on that section is muted)
- **Section repeat** — play an in/out range 1×–8× at the same speed
- **Telemetry HUD** — optional elapsed time and relative altitude from a sibling DJI SRT
- **Flight map** — stored GPS route and a marker synced to the clip clock; OpenStreetMap tiles when they can be fetched and cached locally, otherwise a plain panel
- **Resizable browser and Story tracks**; preview can fill the stage
- **Cancel export** stops a running encode, including photo-only stories
- **Safer export names** — an existing file is never replaced; a taken name is saved as the next free numbered file (`name_1`, `name_2`, …) and that name is shown after export
- **Suggested filename** includes the chosen resolution (for example `_1080p`)

### Share

- **Detail-page export** — one photo or video, saved locally: best quality, or a WhatsApp / Instagram / TikTok preset. Nothing is uploaded. A photo stays an image; a video stays an MP4.

### Reliability

- Local HTTP API accepts only loopback Host and matching Origin (scheme, host, and port)
- Desktop starts with FastAPI 0.162 / Starlette 1.6
- Studio trim, speed, repeat, overlays, HUD, map, fades, and transitions share one clip clock in preview and export

## Upgrade notes

- Opening 2.0.0 uses the existing SQLite index in `%APPDATA%\orga-drone\` (desktop) or your configured data directory. Media files on disk are not modified.
- SQLite upgrades remain forward-only.
- Studio projects from 1.9.0 open as before.

## What this release does not include

- No Windows `orga-drone.exe` / `orga-drone-windows-x64.zip` asset on this GitHub Release
- No MSIX installer, no macOS/Linux binary, no in-app updater
- Ask the library remains rule-based (not an LLM)
- Privacy masks are not tracking and not a legal anonymization guarantee
- Slow motion is not optical-flow interpolation
- Social share destinations and plugins are not included

## Source

Tag `v2.0.0` on `main` at `4bdfe8b`.
