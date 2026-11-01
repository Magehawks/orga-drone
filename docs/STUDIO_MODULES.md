# Studio Frontend Modules (Target)

Status: **target architecture, not the current implementation.** The current
Studio UI is still one file, `src/orga_drone/static/js/studio.js` (~12k lines).
The JavaScript tooling and CI from PR 1 are in place. No frontend module has
been extracted yet.

This document is the canonical map for Studio frontend work. It separates:

1. **Current state** (what exists in the tree).
2. **Target modules** (where code should move).
3. **Rules for new work** (what may depend on what).
4. **Migration order** (small, independently mergeable PRs).

Read this before moving Studio code or adding a new cross-feature dependency.
For product truth, use [`PRODUCT_VISION.md`](PRODUCT_VISION.md). For the rest of
the architecture, use [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Current state

- `studio.js` is an IIFE with roughly 495 function declarations.
- The DOM is the clip data store. Server-rendered `data-*` JSON is read and
  written directly by many functions; there is no clip API.
- There are nine save chains and fourteen `save*` functions with repeated
  debounce, snapshot, and refresh logic.
- Studio routes live in `app.py` (61 of 118 routes). `/studio` builds a large
  view model inline.
- The Python side already has useful domain boundaries:
  `studio_cut.py`, `studio_speed.py`, `studio_transition.py`,
  `studio_estimate.py`, `studio_effect_lane.py`, `studio_lut.py`,
  `studio_hsl.py`, `studio_color_wheels.py`, and the `export/` package.
- Existing JavaScript tests mostly slice `studio.js` as text. New modules must
  use real module tests instead.

Do not treat the current line count as a product goal. Module boundaries and
testability matter more.

## Target modules

All new modules are **ES modules** loaded from the Studio entry. No bundler is
required. The entry remains `static/js/studio.js` until the final slim-down so
existing tests and the PyInstaller static path keep working.

### Core modules

| Module | Responsibility | Public interface | Allowed dependencies | Owns state | Backend endpoints | Tests / fixtures | Forbidden |
|---|---|---|---|---|---|---|---|
| `studio.js` (entry) | Boot, messages, module wiring, history-fetch patch | none; initializes modules | all modules | boot/messages | none | Studio render smoke; existing pytest | feature logic, direct clip writes |
| `studio/api.js` | HTTP and error normalization | `getJson`, `postJson`, `patchJson`, `del`, `StudioApiError` | none | none | all `/api/studio/*` | Node fake-`fetch` tests, error matrix | DOM, clip state, UI copy |
| `studio/state.js` | Project id/title, selection, UI preferences | `get`, `set`, `subscribe`, `persist` | `api`, `format` | `projectId`, `title`, `selected`, `volume` | `PATCH /api/studio/projects/{id}` | Node state/storage roundtrip | clip data, playback time |
| `studio/clip-model.js` | One API over clip `data-*` values | `list`, `get`, `duration`, `sourceRange`, `speed`, `sectionPoint`, `resolveAt`, `read*`, `write*` | `format` | **clip data (DOM as backing store)** | read-only; writes via `settings` | Node fake datasets, timing/transition fixtures | network, preview, save scheduler |
| `studio/settings.js` | Serialized, debounced saves per clip setting | `createSaver({url, method, payload, apply, refresh})` | `api`, `clip-model` | save chains and pending ids | `/image`, `/hsl`, `/color-wheels`, `/detail`, `/frame`, `/masks`, `/overlays`, `/map`, `/hud`, `/saturation-ramp`, `/clip-audio`, `/color-animation`, `/effect-lane` | Node out-of-order/burst tests | foreign DOM; other savers |
| `studio/format.js` | Pure formatting | `formatTime`, `formatLaneTime`, `formatTemplate`, `formatZoom` | none | none | none | Node table tests | DOM, network, state |

### Feature modules

| Module | Responsibility | Public interface | Allowed dependencies | Owns state | Backend endpoints | Tests / fixtures | Forbidden |
|---|---|---|---|---|---|---|---|
| `studio/project-browser.js` | Gallery/switcher, create/open/rename/delete | `initProjectBrowser({root, dialog, messages, defaultTitle, onError, beforeOpen})` | `api` | dialog/focus state | `/api/studio/projects*`, `/open` | Node action routing; Python route tests | Story grid, playback, export |
| `studio/export.js` | Export dialog, options, progress, cancel, success banner | `initExportUi({projectId, messages, pickSaveFile})` | `api`, `format` | dialog/poll/timer state | `/api/studio/export*`, `/api/desktop/pick-save-file` | Node filename/phase tests; `test_export_*` | `state`, `clip-model`, Story DOM |
| `studio/inspector/detail.js` | Sharpen/denoise panel | `createDetailControls({getSelectedClip, refresh, showError, setSaved})` | `clip-model`, `settings`, `format` | panel state | `PATCH /api/studio/{id}/detail` | Node clamp/read/write; Python roundtrip | other inspector panels |
| `studio/inspector/image.js` | Image sliders and Quick Looks | `createImageControls({...})` | `clip-model`, `settings`, `preview` callback | panel state | `/image`, `/look` | Node neutral/clamp; pixel parity | playback, timeline |
| `studio/inspector/color.js` | HSL, wheels, LUT, color points | `createColorControls({...})` | `clip-model`, `settings`, `preview` | panel state | `/hsl`, `/color-wheels`, `/color`, `/color-animation` | Node math; Python pixel parity | direct proxy-cache access |
| `studio/inspector/masks.js` | Mask panel and handles | `createMasks({...})` | `clip-model`, `settings`, `preview` | `selectedMaskId` | `/masks` | Node geometry; Python pixel tests | foreign panels, playback |
| `studio/inspector/overlays.js` | Overlay panel and handles | `createOverlays({...})` | `clip-model`, `settings`, `preview` | selected overlay | `/overlays` | Node geometry; Python pixel tests | foreign panels |
| `studio/inspector/map.js` | Flight-map panel and handles | `createMap({...})` | `clip-model`, `settings`, `preview` | selected map box | `/map` | Node geometry; Python map tests | foreign panels |
| `studio/inspector/hud.js` | Telemetry HUD panel | `createHud({...})` | `clip-model`, `settings`, `preview` | panel state | `/hud` | Node formatting; Python HUD tests | foreign panels |
| `studio/inspector/frame.js` | Zoom/pan panel | `createFrame({...})` | `clip-model`, `settings`, `preview` | panel state | `/frame` | Node clamp; Python frame tests | foreign panels |
| `studio/preview.js` | Layers, blit, stills, proxy scheduling | `apply(hit)`, `invalidateColor(clip)`, `syncMedia(hit)` | `clip-model`, `api`, `studio-lut-webgl.js` | preview media, stills, proxy map | `/preview-frame`, `/playback-proxy`, `/stream`, `/proxy` | existing `.cjs` harnesses, fake media | saves, export, inspector DOM |
| `studio/playback.js` | Clock, video/audio sync | `play`, `pause`, `seek`, `getTime`, `subscribe` | `clip-model`, `preview`, `state` | `projectTimeS`, `playing` | none | Node clock/mapping; manual GUI | settings saves, project browser |
| `studio/timeline.js` | Layout, zoom, playhead, drag, edges | `layout`, `timeToX`, `onSeek`, `onSelect` | `clip-model`, `format`, `state` | `timelineMode`, `zoomIndex`, drag state | `/reorder`, `/photo-duration`, `/cut`, `/section` | Node zoom/mapping; Python timeline tests | preview internals |
| `studio/music.js` | Playlist, audio, timeline spans | `initMusic`, `sync`, `persist` | `api`, `state`, `format`, `timeline` | `tracks`, `musicStartS` | `/music*` | Node playlist/fade math; Python music tests | Story clip writes |
| `studio/history.js` | Undo/redo UI and gesture grouping | `initHistory`, `apply` | `api`, `state` | gesture state | `/api/studio/history/*` | Node gesture tests; Python history tests | clip data |

## Dependency rules

```text
studio.js (entry)
  ├─> project-browser ─> api
  ├─> export ──────────> api, format
  ├─> timeline ────────> clip-model, format, state
  ├─> inspector/* ─────> clip-model, settings, preview (callback)
  ├─> preview ─────────> clip-model, api, studio-lut-webgl
  ├─> playback ────────> clip-model, preview, state
  └─> music ───────────> api, state, format

settings ─> clip-model, api
clip-model ─> format
api, format, state ─> no internal Studio modules
```

1. No module imports `studio.js`.
2. Feature modules do not import other feature modules. Share through core
   modules or injected callbacks.
3. `api.js` is the only place for `fetch` after migration.
4. `clip-model.js` is the only place for clip `dataset` access after migration.
5. `preview.js` is the only place for `window.OrgaLutPreview`.
6. No module writes DOM owned by another module.
7. Dependencies point downward in the diagram. Circular imports are a defect.

## State ownership

| State | Owner | Readers |
|---|---|---|
| `projectId`, `title`, `selected` | `state.js` | entry, inspector, export, timeline |
| Clip data (duration, source, effects) | `clip-model.js` (DOM) | preview, timeline, inspector, playback |
| `projectTimeS`, `playing` | `playback.js` | preview, timeline, music, stills |
| `timelineMode`, `zoomIndex` | `timeline.js` | entry, playback (read only) |
| `tracks`, `musicStartS` | `music.js` | timeline spans, preview audio |
| `selectedMaskId`, overlay/map selection | feature module | preview through callback |
| Export dialog/poll state | `export.js` | entry open button |
| Project dialog state | `project-browser.js` | entry open button |

No module sets `projectTimeS` outside `playback.js`. No module writes clip
`dataset` outside `clip-model.js`. No module manipulates another panel's DOM.

## ES modules vs the current script

Use ES modules for new modules. The app is served over loopback HTTP, so module
imports work in WebView2 and the browser fallback. PyInstaller copies the whole
`static/` tree. Node 22 imports the same modules for tests.

The current two `<script defer>` tags will become one
`<script type="module" src="/static/js/studio.js">`. `studio-lut-webgl.js` stays
a side-effect module and keeps `window.OrgaLutPreview` until `preview.js` owns
that boundary. Do not add a bundler, transpiler, or framework.

## Backend ownership

| Frontend area | Backend modules | Routes |
|---|---|---|
| Clip timing, cut, speed, repeat, transitions | `studio_cut.py`, `studio_speed.py`, `studio_transition.py`, `studio_estimate.py`, `studio_effect_lane.py`, `studio_forward_loop.py` | `/reorder`, `/photo-duration`, `/cut`, `/section`, `/speed`, `/transition`, `/forward-loop`, `/loop-effect` |
| Color, LUT, HSL, wheels, detail | `studio_image.py`, `studio_hsl.py`, `studio_color_wheels.py`, `studio_lut.py`, `studio_detail.py`, `studio_looks.py`, `studio_color_animation.py` | `/image`, `/look`, `/color`, `/hsl`, `/color-wheels`, `/detail`, `/color-animation`, `/saturation-ramp` |
| Preview stills and playback proxy | `studio_preview_frame.py`, `studio_playback_proxy.py` | `/preview-frame`, `/playback-proxy` |
| Masks, overlays, map, HUD, frame, audio | `studio_mask.py`, `studio_overlay.py`, `studio_map.py`, `studio_hud.py`, `studio_frame.py`, `studio_audio.py` | `/masks`, `/overlays`, `/map`, `/hud`, `/frame`, `/clip-audio` |
| Projects, music, history | `studio_history.py`, `studio_audio.py`, `db/__init__.py` | `/api/studio/projects*`, `/music*`, `/history/*` |
| Export | `studio_export.py`, `export/` | `/api/studio/export*` |

Do not move playback/proxy/cache/audio/export color pipelines as part of a
modularization PR. They need their own issue and regression plan.

## Where to change what

Line ranges are approximate and refer to `main` at the time this document was
written. Prefer function names over line numbers.

| Studio change | Current location | Target module |
|---|---|---|
| Export dialog, polling, cancel, success banner | `studio.js:9076-9600` | `studio/export.js` |
| Project gallery/switcher | `studio.js:121-241` | `studio/project-browser.js` |
| Time/template/zoom formatting | `studio.js:492-615, 5065, 6310, 9130` | `studio/format.js` |
| Clip timing, transitions, section points | `studio.js:609-1830, 6708-6770` | `studio/clip-model.js` |
| Preview layers, stills, proxy scheduling | `studio.js:1825-2920, 5318-6170` | `studio/preview.js` |
| Playback clock and audio sync | `studio.js:5830-6170` | `studio/playback.js` |
| Image/HSL/wheels/color controls | `studio.js:2100-3980` | `studio/inspector/*.js` |
| Masks and frame | `studio.js:3988-5310` | `studio/inspector/masks.js`, `frame.js` |
| Music | `studio.js:6266-7800` | `studio/music.js` |
| Title cards, transitions, reuse, loops | `studio.js:7800-9080, 9689-10200` | `studio/timeline.js`, feature modules |
| Overlays, HUD, map | `studio.js:10368-12100` | `studio/inspector/overlays.js`, `hud.js`, `map.js` |

## Test strategy

- New modules get `tests/js/<module>.test.js` and import the real API.
- Pure functions are tested directly; DOM-heavy modules use a small fake DOM
  helper. Do not add jsdom for this.
- Existing text-slicing tests are migrated when their function moves. Do not
  add new tests that do `script.split("function ...")`.
- Cross-language timing/transition cases move to shared JSON fixtures consumed
  by Python and Node.
- Keep the existing pixel-parity tests for LUT/HSL/wheels and FFmpeg chains.
- Manual GUI checks stay in [`PR_E2E.md`](PR_E2E.md) and
  [`LUT_PREVIEW_PARITY.md`](LUT_PREVIEW_PARITY.md).

## Migration order

Each step is independently mergeable and behavior-neutral.

1. **PR 1 (done):** JavaScript tooling and CI for new module paths.
2. **PR 3 (roadmap):** one ES-module entry point; no code moved.
3. **Export UI:** smallest self-contained feature; no app state dependencies.
4. **Project browser + formatting:** pure/small modules.
5. **Clip model (read facade):** wrap existing DOM reads; no behavior change.
6. **Settings scheduler:** one save pipeline for image/HSL/wheels first.
7. **Inspector detail:** first feature module with real module tests.
8. **Color controls:** HSL, wheels, LUT, color points.
9. **Timeline, music, preview/playback.**
10. **Masks, overlays, map, HUD, frame.**
11. **Entry slim-down:** target 500–1,000 lines.

## Non-goals

- No React/Vue/Svelte, no bundler, no TypeScript migration.
- No SQLite or `effect_settings` schema change.
- No UI or behavior change during extraction.
- No rewrite of playback, proxy rendering, audio sync, or export color order.
- No mass formatting of legacy files.
- No new generic `utils/` bucket. Modules are named by responsibility.
