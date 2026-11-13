# Studio Frontend Modules

Status: **eight modules extracted and the settings scheduler now used by Detail
and Image; target architecture still in progress.** The Studio UI still boots
from `src/orga_drone/static/js/studio.js` (~11.4k lines). The JavaScript tooling
and CI from PR 1, the ES-module entry from PR 3, and the export UI, project
browser, formatting, clip model, inspector detail, image save, proxy policy, and
settings modules are in place. Every other feature and the remaining save chains
remain in the entry file.

This document is the canonical map for Studio frontend work. It separates:

1. **Current state** (what exists in the tree).
2. **Target modules** (where code should move).
3. **Rules for new work** (what may depend on what).
4. **Migration order** (small, independently mergeable PRs).

Read this before moving Studio code or adding a new cross-feature dependency.
For product truth, use [`PRODUCT_VISION.md`](PRODUCT_VISION.md). For the rest of
the architecture, use [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Current state

- `studio/sfx-lane.js` owns SFX placement math, clip bars, peak-waveform
  windowing, and the preview gain envelope. `studio.js` paints from the cached
  peaks, persists through the existing SFX routes, and does not decode audio
  during drag or resize. See ADR 0036 and `tests/js/sfx_lane.test.js`.
- `studio/speed-ramp.js` is the pure curve/time-map counterpart to Python.
  `studio/speed-ramp-editor.js` owns the compact curve draft, pointer completion,
  cancellation and numeric controls. The entry injects selection, bounds,
  persistence, timeline positioning and playback callbacks. The editor never
  writes another feature's dataset. `placeRampRegion` stores one Source region
  on the same payload: 1× outside, the existing curve inside. See ADR 0034,
  ADR 0037 and `tests/js/speed_ramp.test.js`.
- `studio/timelapse.js` is the pure target-duration / speed-multiplier draft
  helper (1×–20×) that builds flat ADR 0034 payloads. `studio/timelapse-editor.js`
  owns the Inspector Timelapse draft, conflict messaging and explicit Apply.
  It saves through the shared speed-ramp endpoint and never invents a second
  timing model. See `tests/js/timelapse.test.js` and `studio_timelapse.py`.

- `studio/color-compare.js` owns the temporary hold input, comparison request,
  abort/decode token and decoded picture. The entry injects the selected paused
  clip/source-time identity, save settling and redraw callback. It never writes
  clip data, history or caches. The existing preview-frame route neutralizes only
  comparison inputs while retaining technical conversion; the compositor uses
  the temporary picture for the selected layer, without replacing either normal
  still owner. Release restores the normal rendering path immediately.

- `studio/color-workspace.js` owns pure Creative/Pro helpers: per-clip Quick Look
  request tokens, inspector-refresh gating when selection changes mid-flight, and
  grade-summary part formatting. The entry still owns DOM fills and saves.
- `studio/grade-api.js` owns Grade HTTP helpers (GET/PUT/wrap/convert-managed/
  `postGradeCommand`) and primaries step upsert helpers for ADR 0035 managed
  grades. `studio/managed-color-editor.js` owns the Managed Color Workspace
  inspector panel (wrap/convert/reset and primaries sliders). The entry mounts
  the panel and refreshes it from image-inspector fill; preview invalidation
  stays in the entry. `studio/managed-curve-editor.js` owns the seven managed
  curve families (RGB/luma/hue-sat maps) against the same grade PUT path.
  `studio/managed-selection-editor.js` owns linear/radial/brush masks and
  RGB/HSL/luma qualifiers bound to a managed step. See
  `tests/js/grade_api.test.js` and `tests/js/managed_color_editor.test.js`.
  `studio/managed-lut-editor.js` owns the managed creative-lut-v1 step against
  confined local `.cube` assets. `studio/managed-step-editor.js` owns the
  serial step list (enable/mix/reorder) via `postGradeCommand`.
  `studio/preview-token.js` owns async preview identity tokens (#363).
  Parameter body edits still use full grade PUT until a params command exists.

- `studio/scopes/` owns ScopeFrameV1 validation, fixture frames, reference
  histogram/waveform/parade/vectorscope accumulation, canvas paint, the Pro
  scopes panel (#362), the #366 tap controller/capability probe, and the
  `managed-preview-frame-v1` producer (`preview-tap.js`) that tags #359
  preview-frame stills for live scopes. Display blit / CSS / untagged WebGL
  remain refused; fixtures stay disclosed.

- `studio/control-bridge.js` owns the opt-in local control polling handshake and
  compact Studio disclosure. The entry injects snapshots, queued-save settling,
  and canonical image/color/HSL/wheels/detail/inspector/history/preview callbacks.
  The bridge never imports the entry, saves clip properties itself, or simulates
  editing clicks. Canonical values use existing image/color/HSL/wheel/detail
  writers and invalidate existing preview/proxy caches. Preview acknowledgement
  means refresh requested, not confirmed rendering. See `docs/CONTROL_API.md` and
  ADR 0032.

- `studio.js` is an ES module entry (IIFE internally) with roughly 465 function
  declarations.
- `studio/export.js` owns the export dialog, options, progress, cancel, and
  success-banner behavior. `studio.js` only imports and initializes it.
- `studio/project-browser.js` owns the create/open/rename/delete actions,
  confirmation prompts, dialog lifecycle, and project action errors.
- `studio/format.js` owns the shared time, lane-time, template, and export-clock
  formatters. Frame zoom formatting remains in the entry because it depends on
  the frame clamp.
- `studio/clip-model.js` is the DOM-backed clip facade. It reads identity, type,
  availability, source ranges, durations, playback speed, media URLs, and
  display text, and exposes one narrow `setClipField` writer. It does not cache,
  fetch, persist, or schedule work.
- `studio/settings.js` owns serialized saves with optional debounce and one
  error callback. The Detail and Image modules are migrated consumers; HSL,
  wheels, masks, overlays, map, HUD, frame, saturation ramp, audio, color
  animation, and effect-lane saves remain in the entry.
- `studio/inspector/detail.js` owns the sharpen/denoise panel: read/write/clamp,
  fill, input/reset bindings, and its scheduled save. `studio.js` only creates
  it and calls `fill` during inspector refresh.
- `studio/inspector/image-save.js` owns the image-adjust save chain: payload,
  stale-response guard, dataset write, save-state, and preview refresh. It uses
  `settings.js` and shares the existing `imageSaveChain` with saturation-ramp
  saves, so both remain in one serialization order.
- `studio/proxy-policy.js` owns the pure LUT proxy eligibility, WebGL handling
  gate, and cache-key rules. `studio.js` still reads clip state and owns the
  proxy scheduling, fetch, cache, and UI-chip orchestration.
- The DOM is the clip data store. `studio/clip-model.js` is the read/write
  facade for migrated fields, but legacy functions still read and write
  `data-*` directly. There is no separate clip shadow state.
- The entry still owns eight serialization chains and twelve `save*` functions
  with repeated debounce, snapshot, and refresh logic. The Image chain delegates
  to `studio/settings.js` while sharing `imageSaveChain` with saturation-ramp
  saves.
- Studio routes live in `app.py` (61 of 118 routes). `/studio` builds a large
  view model inline.
- The Python side already has useful domain boundaries:
  `studio_cut.py`, `studio_speed.py`, `studio_transition.py`,
  `studio_estimate.py`, `studio_effect_lane.py`, `studio_lut.py`,
  `studio_hsl.py`, `studio_color_wheels.py`, and the `export/` package.
- Export, project browser, formatting, the settings scheduler, inspector detail,
  image save, and proxy policy now have direct module tests. Older areas still
  use text-slicing tests; migrate those when their code moves.

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
| `studio/clip-model.js` | **Implemented.** DOM-backed clip facade | `listClipElements`, `findClip`, `clipId`, `clipKind`, `clipIsAvailable`, `clipCanPlay`, `clipHasProxy`, `clipMediaId`, `clipFilename`, `clipDisplayTitle`, `clipDisplaySubtitle`, `clipEffectiveDuration`, `clipSourceIn`, `clipSourceOut`, `clipMediaDuration`, `clipPlaybackSpeed`, `clipPhotoDuration`, `clipStreamUrl`, `clipProxyUrl`, `clipPreviewUrl`, `clipThumbUrl`, `clipDuration`, `setClipField` | none | **clip data (DOM as backing store)** | read-only; writes stay caller-owned | `tests/js/clip_model.test.js`; fake datasets | network, persistence, preview, save scheduler, shadow state |
| `studio/settings.js` | **Implemented (Detail and Image).** Serialized saves with optional debounce | `createSaver({url, method, payload, apply, refresh, errorMessage, onError, headers, fetchImpl, readJson, debounceMs, setTimeoutImpl, clearTimeoutImpl, serialize, getChain})` | none; fetch/JSON/timers are injected | save chains, pending keys, debounce timer | `/detail`, `/image`; remaining endpoints move with their chains | `tests/js/settings.test.js`; fake fetch/timers | foreign DOM; other savers |
| `studio/format.js` | **Implemented.** Shared pure formatting | `formatTemplate`, `formatTime`, `formatLaneTime`, `formatExportDuration` | none | none | none | `tests/js/format.test.js` | DOM, network, state |
| `studio/proxy-policy.js` | **Implemented.** Pure LUT proxy policy | `evaluateLutProxyEligibility`, `evaluateLutWebglHandling`, `lutProxyPrepareKey` | none | none | none | `tests/js/proxy_policy.test.js`; existing proxy harnesses | DOM, fetch, timers, preview state, cache access |

### Feature modules

| Module | Responsibility | Public interface | Allowed dependencies | Owns state | Backend endpoints | Tests / fixtures | Forbidden |
|---|---|---|---|---|---|---|---|
| `studio/project-browser.js` | **Implemented.** Server-rendered project list actions: create/open/rename/delete, prompts, dialog lifecycle, errors | `createProjectBrowser({root, documentImpl, dialog, openButton, closeButton, defaultTitle, messages, fetchImpl, readJson, navigate, reload, prompt, confirm, showError, beforeOpen})` returns `{init, destroy}` | none; browser APIs and JSON reader are injected or defaulted | dialog/focus state, action errors | `/api/studio/projects*`, `/open`, `PATCH`, `DELETE` | `tests/js/project_browser.test.js`; Python route tests | Story grid, playback, export, client-side project list rendering |
| `studio/export.js` | **Implemented.** Export dialog, options, progress, cancel, success banner | `createExportUi({projectId, documentImpl, root, messages, fetchImpl, now, setTimeoutImpl, clearTimeoutImpl, setIntervalImpl, clearIntervalImpl, elements})` | `format`; browser APIs are injected or defaulted | dialog, poll, timer, filename, and success state | `/api/studio/export*`, `/api/desktop/pick-save-file` | `tests/js/export_ui.test.js`; `test_export_*` | `state`, `clip-model`, Story DOM, playback, export backend |
| `studio/inspector/detail.js` | **Implemented.** Sharpen/denoise panel | `createDetailControls({getSelectedClip, getClipById, setSaved, showError, refresh, errorMessage, fetchImpl, readJson})`; returns `bind`, `destroy`, `fill`, `queueSave`, `read`, `write`, `neutral`, `clamp` | `settings`; DOM/fetch/timers injected | panel DOM and detail save | `PATCH /api/studio/{id}/detail` | `tests/js/inspector_detail.test.js`; Python roundtrip | other inspector panels |
| `studio/inspector/image-save.js` | **Implemented.** Image-adjust save chain | `createImageAdjustSaver({getClipById, readAdjust, writeAdjust, isSelected, fill, refreshPreview, setSaved, showError, errorMessage, headers, fetchImpl, readJson, debounceMs, setTimeoutImpl, clearTimeoutImpl, serialize, getSharedChain})`; returns `queue`, `flush`, `whenIdle` | `settings`; clip/DOM/fetch/timers injected | pending clip capture for one save | `PATCH /api/studio/{id}/image` | `tests/js/image_save.test.js`; `tests/js/lut_preview.cjs` | other save chains, preview rendering |
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

The diagram is the target dependency shape. In the current tree,
`settings.js` and `clip-model.js` import no internal Studio modules;
`export.js` imports `format.js`; `inspector/detail.js` and
`inspector/image-save.js` import `settings.js`.

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
| Clip data (duration, source, effects) | `clip-model.js` + DOM dataset (still authoritative) | preview, timeline, inspector, playback |
| `projectTimeS`, `playing` | `playback.js` | preview, timeline, music, stills |
| `timelineMode`, `zoomIndex` | `timeline.js` | entry, playback (read only) |
| `tracks`, `musicStartS` | `music.js` | timeline spans, preview audio |
| `selectedMaskId`, overlay/map selection | feature module | preview through callback |
| Export dialog/poll state | `export.js` | entry open button |
| Project dialog state | `project-browser.js` | entry open button |

Target rule after migration: no module sets `projectTimeS` outside
`playback.js`, no module writes clip `dataset` outside `clip-model.js`, and no
module manipulates another panel's DOM. Until then, legacy direct writes remain
documented in the entry file.

## ES modules vs the current script

Use ES modules for new modules. The app is served over loopback HTTP, so module
imports work in WebView2 and the browser fallback. PyInstaller copies the whole
`static/` tree. Node 22 imports the same modules for tests.

The entry point is now a single
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
| Export dialog, polling, cancel, success banner | `studio/export.js` | `studio/export.js` (implemented) |
| Project gallery/switcher actions | `studio/project-browser.js` | `studio/project-browser.js` (implemented) |
| Clip identity, type, display text, title-card writes | `studio/clip-model.js` | `studio/clip-model.js` (implemented) |
| Sharpen/denoise panel | `studio/inspector/detail.js` | `studio/inspector/detail.js` (implemented) |
| Image adjust save chain | `studio/inspector/image-save.js` | `studio/inspector/image-save.js` (implemented) |
| Time/template formatting | `studio/format.js` | `studio/format.js` (implemented) |
| Frame zoom formatting | `studio.js` (`formatZoom`) | stays in the entry because it uses the frame clamp |
| Clip timing, transitions, section points | `studio.js:609-1830, 6708-6770` | `studio/clip-model.js` |
| LUT proxy eligibility, WebGL gate, cache key | `studio/proxy-policy.js` | `studio/proxy-policy.js` (implemented) |
| Preview layers, stills, proxy scheduling | `studio.js:1825-2920, 5318-6170` | `studio/preview.js` |
| Playback clock and audio sync | `studio.js:5830-6170` | `studio/playback.js` |
| Image/HSL/wheels/color controls | `studio.js:2100-3980` | `studio/inspector/*.js` |
| Masks and frame | `studio.js:3988-5310` | `studio/inspector/masks.js`, `frame.js` |
| Music | `studio.js:6266-7800` | `studio/music.js` |
| Title cards, transitions, reuse, loops | `studio.js:7800-9080, 9689-10200` | `studio/timeline.js`, feature modules |
| Overlays, HUD, map | `studio.js:10368-12100` | `studio/inspector/overlays.js`, `hud.js`, `map.js` |

## Clip model boundaries

`studio/clip-model.js` currently supports these clip dataset fields:

- Identity/type: `studioId`, `kind`, `available`, `canPlay`, `hasProxy`, `mediaId`
- Media text/URLs: `filename`, `displayTitle`, `displaySubtitle`, `streamUrl`, `proxyUrl`, `previewUrl`, `thumb`
- Timing values: `effectiveDuration`, `sourceIn`, `sourceOut`, `mediaDuration`, `playbackSpeed`, `photoDuration`

Writes are intentionally narrow: `setClipField` accepts only `photoDuration`,
`effectiveDuration`, `title`, `subtitle`, `background`, `displayTitle`, and
`displaySubtitle`. It changes the dataset only; callers still own persistence,
layout, and preview refreshes.

Migrated callers include clip enumeration, ordered ids, display names, playhead
identity checks, adjustable clip selection, active-clip checks, clip selection
identity/type/filename, title-card remove identity, and title-card display/field
writes. This step routed 34 direct field accesses through the model; 269 remain
in the entry. `studio.js` changed from 11,388 to 11,399 lines; the small increase
is the import block.

Remaining direct dataset access stays in the legacy entry for areas that are
still tightly coupled: playback clock and audio sync, source/timing readers,
proxy eligibility and cache invalidation, WebGL decisions, HSL/color-wheel save
chains, timeline drag and transition math, forward-loop state,
masks/overlays/map/HUD, export, and non-migrated title-card field reads. These
areas must not be migrated as part of this clip-model step.

New modules should use the clip API. Existing legacy access is allowed until
the relevant area is migrated. There is no lint rule enforcing the boundary yet;
enforce it only after the migration is complete.

## Test strategy

- New modules get `tests/js/<module>.test.js` and import the real API.
- Current direct module tests: `export_ui.test.js`, `project_browser.test.js`, `format.test.js`, `settings.test.js`, `inspector_detail.test.js`, `image_save.test.js`, `proxy_policy.test.js`, `clip_model.test.js`.
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

Each approved extraction step is independently mergeable and behavior-neutral.
The target map does not require refactoring unrelated areas for every fix/feature.
Select validation by risk using [`PR_E2E.md`](PR_E2E.md); preserve the focused
module and sensitive-pipeline regression expectations above.

1. **PR 1 (done):** JavaScript tooling and CI for new module paths.
2. **PR 3 (done):** one ES-module entry point; no code moved.
3. **PR 4 (done):** export UI extracted to `studio/export.js`; no app state dependencies.
4. **PR 5 (done):** project browser and shared formatting extracted; server-rendered list stays server-rendered.
5. **Clip model (done):** read facade plus narrow writes; DOM dataset remains authoritative; playback, proxy, and effect save chains stay legacy.
6. **Settings scheduler (Detail and Image done):** `studio/settings.js` with serialized and optional debounced saves; Detail and Image are migrated. HSL/wheels chains follow.
7. **Inspector detail (done):** `studio/inspector/detail.js` with direct module tests.
8. **Proxy policy (done):** pure LUT proxy eligibility, WebGL gate, and cache key; scheduling stays in the entry.
9. **Color controls:** HSL, wheels, LUT, color points.
10. **Timeline, music, preview/playback.**
11. **Masks, overlays, map, HUD, frame.**
12. **Entry slim-down:** retain boot/wiring responsibilities as approved slices
    are extracted; no line-count quota or blanket extraction prerequisite.

## Non-goals

- No React/Vue/Svelte, no bundler, no TypeScript migration.
- No SQLite or `effect_settings` schema change.
- No UI or behavior change during extraction.
- No rewrite of playback, proxy rendering, audio sync, or export color order.
- No mass formatting of legacy files.
- No new generic `utils/` bucket. Modules are named by responsibility.
