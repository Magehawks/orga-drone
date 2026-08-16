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
| Packaging | setuptools (`src` layout); PyInstaller onefolder Windows zip |
| Tests | pytest under `tests/` |
| CI | GitHub Actions: Ruff, MyPy, pytest on pull requests |

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

## Package layout (`src/orga_drone/`)

| Area | Responsibility |
|------|----------------|
| `app.py` | FastAPI routes (HTML + APIs) |
| `config.py` | Settings, paths, env |
| `desktop.py` | Desktop window / port discovery / native folder + save + open pickers; Windows open/reveal of local files |
| `db/` | Schema, migrations, queries |
| `scan/` | Full rescan of library roots |
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
| `studio_projects` | Studio projects (`title`, timestamps); deleting a project never deletes `media` |
| `studio_clips` | Story clips per project: media refs (`item_kind='media'`, path + identity + optional `source_media_id`) or generated Title Cards (`item_kind='title_card'`, NULL path, title/subtitle/duration/background); start/end, speed, volume, outgoing `transition` + `transition_duration_s`, effect_settings JSON; survives rescan |
| `studio_audio_clips` | Optional sequential soundtrack playlist (up to 8 songs; `duration_s`; volume/fades; loop when N=1; read-only path outside library roots allowed; not library media) |
| `app_state` | Small key/value app pointers (currently last-opened Studio project id) |
| `geocode_cache` | Offline place cache |

## Scan / index pipeline

Core: `scan_root()` / `scan_all_roots()` in `src/orga_drone/scan/__init__.py`.

1. Recursively find media files under a root
2. Clear indexed media for that root (**full rescan**; `media_meta` and
   `studio_clips` kept)
3. Parse → upsert assets/media
4. Relink user meta + Studio membership + apply auto-tags
5. Rebuild flows, then sessions
6. Mark root scanned

HTTP triggers in `app.py`: add root, scan one root, scan all.

Library scans run in a **background thread** with an in-memory job
(`src/orga_drone/scan/jobs.py`). The browser polls `GET /api/scan-jobs/{id}`
for phase/counters (discovering / indexing / grouping). Full-rescan semantics
are unchanged; jobs are not persisted in SQLite. At most one library scan runs
at a time.

## UI surfaces

Templates under `src/orga_drone/templates/` (dashboard/browse, library,
detail, map, duplicates, studio, …). Static assets under `src/orga_drone/static/`.
Studio page: Jinja layout + `static/js/studio.js` (project browser/switcher,
project title, reorder/duration/cut APIs; `GET /studio` restores the last-opened
project from `app_state`; synced Story preview via `/stream`/`/proxy`; local MP4
export via async job
`POST /api/studio/export` + poll `GET /api/studio/export/jobs/{id}` with
determinate progress in the export dialog (elapsed time, ETA, current clip
label; within-clip ffmpeg progress). On success the dialog closes and Studio
shows a dismissible banner with Open video / Show in folder
(`POST /api/studio/export/open` and `/reveal`; Windows desktop; last
successful output only). Desktop save dialog. Optional project soundtrack
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
add folder → full scan/parse → SQLite index → browse / map / detail
                                         → optional Studio curation
                                         → optional rename, merge, export, dupes
```

## Tests

- Location: `tests/`
- Style: domain unit tests + FastAPI `TestClient` smoke tests
- Prefer covering parsing, sessions, search, dupes, meta, and route behavior
  when those areas change

## Design constraints for new work

1. Stay local-first; do not require cloud accounts.
2. Do not claim plugins, albums, or incremental scan until implemented.
3. Prefer small modules in existing package areas over new top-level frameworks.
4. Preserve `media_meta` and `studio_clips` across rescans.
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
- Agent summary: `AGENTS.md`
