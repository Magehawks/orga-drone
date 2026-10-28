# Architecture

High-level description of the **current** Orga Drone codebase.
Do not invent layers, services, or plugins that are not present.

## Stack

| Layer | Choice |
|-------|--------|
| Language | Python ≥ 3.11 |
| Web UI | FastAPI + Jinja2 templates + static JS/CSS |
| Desktop shell | pywebview (Edge WebView2 on Windows); browser fallback; native folder picker via `FileDialog.FOLDER` |
| Index | SQLite in the OS app-data directory |
| Media | Streamed from configured library folders (not embedded) |
| Thumbnails / merge | Pillow / pillow-heif; `imageio-ffmpeg` or system ffmpeg |
| Maps | Leaflet (vendored) + OpenStreetMap tiles |
| Studio icons | Lucide SVGs (vendored under `static/vendor/lucide/`, ISC) |
| App icon | Local PNG/ICO under `static/icons/` (Windows EXE from `packaging/assets/orga-drone.ico`) |
| Packaging | setuptools (`src` layout); PyInstaller onefolder Windows zip. itch.io butler process is documented in `packaging/itch/` and is not an in-app updater |
| Tests | pytest under `tests/` |
| CI | GitHub Actions on pull requests: Ruff, MyPy, pytest, plus a separate **App journey smoke** check (`tests/test_pr_journey_smoke.py`, synthetic JPEG, no private library). Windows onefolder zip on manual dispatch and `vX.Y.Z` tags (draft release; a maintainer publishes after the MOTW smoke test). See `docs/PR_E2E.md` and `packaging/README.md`. |

Entry: `python -m orga_drone` → `src/orga_drone/__main__.py` →
`create_app()` in `src/orga_drone/app.py`.

## Runtime data (outside the repo)

Default data dir examples: `%APPDATA%\orga-drone\` (Windows).
Override: `ORGA_DRONE_DATA_DIR`.

| Path | Content |
|------|---------|
| `{data_dir}/orga-drone.sqlite3` | Library index |
| `{data_dir}/thumbs/` | Generated thumbnails/previews |
| `{data_dir}/theme.json` | Theme preference |
| `{data_dir}/logs/studio-export.log` | Short Studio export job lines |
| `{data_dir}/logs/studio-export-ffmpeg.log` | Full ffmpeg command + stderr on export failure |

Media files stay on disk under user-chosen library roots.

An itch.io app update, when a maintainer later publishes one, replaces the
install folder only. It does not write the library database. Direct ZIP
installs (GitHub or the itch.io website) are not tracked by the itch.io app,
so they do not auto-update. See `packaging/itch/README.md`.

## Package layout (`src/orga_drone/`)

| Area | Responsibility |
|------|----------------|
| `app.py` | FastAPI routes (HTML + APIs) |
| `local_http.py` | Loopback Host plus Origin scheme/host/port checks; writes need a matching Origin (or same-origin Sec-Fetch-Site and Referer) |
| `config.py` | Settings, paths, env |
| `desktop.py` | Desktop window / port discovery / native folder + save + open pickers; Windows open/reveal of local files; MOTW-safe copy of WebView2 DLLs (see `packaging/README.md`) |
| `db/` | Schema, migrations, queries |
| `scan/` | Rescan of library roots; unchanged files skip metadata extraction |
| `parse/` | Filenames, SRT, EXIF, generic media |
| `group/` | Flows (FAT32 splits) + sessions |
| `search/` | Rule-based Ask the library (DE/EN) |
| `dupes/` | Heuristic duplicate detection |
| `geocode/` | Offline reverse geocode + cache |
| `ops/` | Rename, flow merge |
| `export/` | Spot GeoJSON; Studio MP4 config + ffmpeg encoder; in-memory export jobs + last-success slot; optional music mix |
| `studio_export*.py` / `app_prefs.py` | Studio export orchestration, resolution rules, last-dir prefs |
| `thumbs.py` | Thumbnail / preview generation |
| `i18n.py` + `locales/` | DE/EN strings |
| `templates/` + `static/` | UI |

## Data model (SQLite)

Schema lives in `src/orga_drone/db/__init__.py` (`SCHEMA` + `_migrate`).

| Table | Purpose |
|-------|---------|
| `library_roots` | Indexed folders |
| `assets` | Found files (incl. sidecars) |
| `media` | Videos/photos + metadata, GPS, track JSON, auto-tags; optional `width`/`height` |
| `flows` / `flow_items` | Split-clip groups |
| `sessions` / `session_items` | Heuristic flight sessions |
| `media_meta` | User stars/favorites/tags/notes (survives rescan) |
| `albums` | User-named library albums (independent of `studio_projects`) |
| `album_items` | Non-destructive media references (`media_path` + `identity_key` + optional `source_media_id`); one file may appear in several albums; survives rescan; listed as offline when the file is not on disk |
| `studio_projects` | Studio projects (`title`, timestamps); deleting a project never deletes `media` |
| `studio_clips` | Story clips per project: media refs (`item_kind='media'`, path + identity + optional `source_media_id`) or generated Title Cards (`item_kind='title_card'`, NULL path, title/subtitle/duration/background); start/end, speed, volume, outgoing `transition` + `transition_duration_s`, `effect_settings` JSON (photo and video image sliders under `image`; video saturation ramp under `saturation_ramp`; timed overlays under `overlays`; privacy masks under `masks`; zoom and pan under `frame`; optional flight-map box under `map`, drawn from stored GPS over cached OpenStreetMap tiles when a tile can be fetched, otherwise a plain panel; optional video telemetry HUD under `hud`; optional `loop_to_soundtrack` boolean that repeats one video section forward to a known soundtrack duration at preview and export time, without storing that duration; optional `loop_transition` (`crossfade`, `cinematic`, or experimental `match`), `loop_transition_s` (0.5–2.0, or 0.5–5.0 for cinematic), and `loop_transition_curve` (`linear` or `smooth`, cinematic only) on the same JSON, used for a soundtrack-length repeat and for a manual 1–8 repeat, applied as an overlap that shortens each extra play, clamped when the section is shorter, and omitted when off; `match` stores a local seam under `loop_match` and keeps the user's range when that seam is not confident); survives rescan |
| `studio_audio_clips` | Optional sequential soundtrack playlist (up to 8 songs; `duration_s`; volume/fades; loop when N=1; read-only path outside library roots allowed; not library media) |
| `app_state` | Small key/value app pointers (currently last-opened Studio project id) |
| `geocode_cache` | Offline place cache |

Studio Undo/Redo keeps up to 50 snapshots of one project's `studio_clips` rows in process memory (`studio_history`). It is not a table. Restarting the app drops the stack. Restoring a snapshot rewrites only that project's clip rows.

The transport trash button, the Delete key, and the Story clip context menu remove one selected clip through the existing `/studio/{id}/remove` route. That drops the Story row only. The media file stays. Delete applies when focus is on the Story track or the playhead and no dialog is open. Backspace is not a remove shortcut. Opening the clip menu focuses its item and closing it returns focus to the control that was active before.

Removing a cut joins the clip with the one before it through `POST /api/studio/{id}/merge-previous`. The left row keeps its id and grows to the right row's source end. The right row is deleted. Settings are copied only when they match, including masks and grade. Overlay times shift back onto one timeline. A saturation ramp is kept when the right-hand times are the left-hand ramp shifted by the left source duration. Source ends must meet within 0.001 s. A repeat, a soundtrack loop, a different speed, or a transition other than a cut between the two clips is refused. The refusal does not become an Undo step. A successful join is one Undo step in the existing story history.

Another scene from the same original is `POST /api/studio/{id}/reuse-source`. It inserts one new `studio_clips` row immediately after the clicked video, in story order, and shifts only the clips that follow. The new row copies the media path, identity, and library id, stores the chosen source range (NULL, NULL when it covers the whole file), and starts with empty effects, speed 1, and a hard cut out. The clicked row is not updated. The preview seek during the draft is client-side and does not write. Cancel writes nothing. A refusal is not an Undo step. A successful add is one Undo step; Undo removes the new row and restores the later positions.

Dragging a video clip's left or right edge on the Story timeline changes that clip's source start or source end through the existing section PATCH. The drag stays inside the file duration and at least 0.05 s. One completed drag is one Undo step. Neighboring clips keep their source ranges and effects; their story positions move only because this clip's length changed. There is no snap. Photos, title cards, and videos with an unknown duration have no edge handles. The original file is not modified.

A cut or a trimmed video also stores one `studio_originals` row for that project and file. Removing the Story clips does not remove it, and it is still there after a restart. `POST /api/studio/media/{media_id}/reuse-source` inserts one new clip from that row, at the end or before `before_id`, in one Undo step. The Original row is not part of the session snapshot, so Undo of the new scene leaves the Original in the Story browser.

## Scan / index pipeline

Core: `scan_root()` / `scan_all_roots()` in `src/orga_drone/scan/__init__.py`.

1. If the root cannot be listed (missing drive or disconnected share), keep
   the existing catalog and report the source offline. Do not clear `media`
   or user metadata. A child folder that cannot be listed keeps the catalog
   entries already stored under that folder; the rest of the root is scanned.
2. Recursively find media files under a root
3. Skip metadata extraction when the stored asset size and mtime match
   (ADR 0020). A sibling SRT is included by its own size and mtime. Parse new
   or changed files before replacing any index rows.
   If the source disappears during that read, keep the existing catalog.
4. Drop index rows for this root whose paths were not found, and only if the
   root is still listable. Paths under a child folder that could not be listed
   stay. `media_meta`, `album_items`, and `studio_clips` stay.
   An empty but listable folder is a confirmed deletion.
5. Upsert new or changed files, then relink user meta, album membership,
   Studio membership, and auto-tags for those parsed files. A size/mtime
   match still refreshes SRT/LRF flags and Live Photo pairing from filenames.
6. Rebuild flows, then sessions (this still runs when every file was unchanged)
7. Mark root scanned

HTTP triggers in `app.py`: add root, scan one root, scan all.

Library scans run in a **background thread** with an in-memory job
(`src/orga_drone/scan/jobs.py`). The browser polls `GET /api/scan-jobs/{id}`
for phase/counters (discovering / indexing / grouping). Jobs are not persisted
in SQLite. At most one library scan runs at a time.

## UI surfaces

Templates under `src/orga_drone/templates/` (dashboard/browse, library,
detail, map, duplicates, studio, …). Static assets under `src/orga_drone/static/`.
Browse Timeline (`browse_timeline.py`, `view=timeline`) groups the same indexed
photos and videos by recording date. It reuses Browse filters and pagination
and does not call the Studio story timeline.
Studio page: Jinja layout + `static/js/studio.js` (project browser/switcher,
project title, reorder/duration/cut APIs; `GET /studio` restores the last-opened
project from `app_state`; synced Story preview via `/stream`/`/proxy`; local MP4
export via async job
`POST /api/studio/export` + poll `GET /api/studio/export/jobs/{id}` with
determinate progress in the export dialog (one elapsed-time readout, current
clip label; within-clip ffmpeg progress, then the final concat re-encode, so
the bar reaches about 100% when that encode ends). An export never replaces an existing file.
If the requested name is taken, or it is a library source, soundtrack, or project
asset, the file is written to the next free numbered name (`video.mp4`, then
`video_1.mp4`, then `video_2.mp4`). That name is claimed exclusively. If it is
taken before the claim, the next free name is used. The success banner shows the
name that was written. On success the dialog closes and Studio
shows a dismissible banner with Open video / Show in folder
(`POST /api/studio/export/open` and `/reveal`; Windows desktop; last
successful output only). The media detail page exports that one photo or
video through the same job, cancel, and open/reveal routes
(`POST /api/media/{id}/export`). Rating, tags, notes, albums, Studio, export,
rename, and flow merge are Organize / Share / File tabs on that page; preview,
metadata, location, and Single clip / Complete flight stay outside the tabs.
A photo is a local still (best quality copies
a readable image when the grade is neutral; WhatsApp, Instagram, and TikTok
are JPEG presets, not uploads). Brightness, contrast, saturation, and warmth
use the Studio ffmpeg grade before that preset. Neutral omits the grade.
The library file is not modified. Preview uses the same CSS approximation
as Studio. A video is one clip on the Studio encoder (best quality uses the
highest existing resolution; those three presets are a 1080×1920 frame with
the picture fitted inside it). Desktop save dialog. Optional project soundtrack
playlist (`studio_audio_clips`, up to 8 songs) is previewed and mixed into the
MP4; Title Cards are
generated `studio_clips` (HTML preview + ephemeral Pillow still on export);
visual transitions Cut / Fade through black / Crossfade persist on the outgoing
clip and render in preview + MP4). The Story timeline is a shared time canvas
(`px/s` Fit/zoom; ruler, clips, playhead and the read-only soundtrack coverage
spans share one mapping; soundtrack tile width follows each song’s effective
duration; transitions are labeled boundary overlays). Selected vs
playhead-active clips use distinct chrome; the Inspector names the selected
object. The open project title sits with a labeled **Projects** switcher;
**Export** is the share action; **Clear Studio** is on the Story toolbar and
clears `studio_clips` only. Transport/editing controls use vendored Lucide icons
(`static/vendor/lucide/`; see README there). Export cancel/abort remains out of
scope.

Typical user flow:

```text
add folder → scan/parse (unchanged files skip extraction) → SQLite index → browse / map / detail
                                         → optional Studio curation
                                         → optional rename, merge, export, dupes
```

## Tests

- Location: `tests/`
- Style: domain unit tests + FastAPI `TestClient` smoke tests
- Pull-request journey: `tests/test_pr_journey_smoke.py` walks import → browse → Studio with a generated JPEG and a temporary data directory. CI reports it as **App journey smoke**. See `docs/PR_E2E.md`.
- Prefer covering parsing, sessions, search, dupes, meta, and route behavior
  when those areas change

## Design constraints for new work

1. Stay local-first; do not require cloud accounts.
2. Do not claim plugins or incremental scan until implemented.
3. Prefer small modules in existing package areas over new top-level frameworks.
4. Preserve `media_meta`, `album_items`, and `studio_clips` across rescans.
5. Path operations for library media must stay confined under library roots.
   Studio music is a documented exception: read-only soundtrack paths (up to 8
   sequential songs per project), including files outside library folders
   (ADR 0008).
6. Record significant architecture choices in `docs/decisions/`.

## Related docs

- Product: `docs/PRODUCT_VISION.md`
- Roadmap: `docs/ROADMAP.md`
- Decisions: `docs/decisions/`
- Packaging: `packaging/README.md`
- Pull-request journey check: `docs/PR_E2E.md`
- Agent summary: `AGENTS.md`
