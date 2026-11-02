# Studio Architecture Audit

Status: **checkpoint after PR #247.** This document describes the current
implementation, not the target architecture. Product behavior is unchanged by
PR 8.

## 1. Current architecture state

The Studio UI still boots from one large entry module:

- `src/orga_drone/static/js/studio.js` (11,399 lines, 466 function declarations)
- `src/orga_drone/static/js/studio-lut-webgl.js` (side-effect module; exposes
  `window.OrgaLutPreview`)

Seven modules are extracted under `src/orga_drone/static/js/studio/`:

| Module | Lines | Responsibility |
|---|---:|---|
| `clip-model.js` | 190 | DOM-backed clip read facade and narrow `setClipField` writer |
| `export.js` | 621 | Export dialog, options, progress, cancel, success banner |
| `format.js` | 28 | Shared time, lane-time, template, and export-clock formatting |
| `project-browser.js` | 221 | Project create/open/rename/delete and dialog lifecycle |
| `proxy-policy.js` | 51 | Pure LUT proxy eligibility, WebGL gate, cache-key shape |
| `settings.js` | 104 | Serialized/debounced save scheduler with error callback |
| `inspector/detail.js` | 175 | Sharpen/denoise panel and its scheduled save |

The entry remains the owner of the Story timeline, inspector wiring, playback,
preview, proxy orchestration, music, history gestures, masks/overlays/map/HUD,
transitions, title cards, and most save chains.

## 2. Actual module boundaries

### Implemented boundaries

- `format.js` is pure and has no internal imports.
- `clip-model.js` is pure DOM/dataset access and has no internal imports.
- `proxy-policy.js` is pure policy evaluation and has no internal imports.
- `settings.js` owns network/timer scheduling and has no internal imports; fetch,
  JSON reading, and timers are injectable.
- `project-browser.js` injects browser APIs and has no internal imports.
- `export.js` imports `format.js` for export-clock formatting.
- `inspector/detail.js` imports `settings.js` and injects DOM, fetch, JSON, and
  timers.

### Still mixed

- `studio.js` owns feature logic and direct DOM/dataset writes.
- `inspector/detail.js` writes `clip.dataset.detail` directly rather than going
  through `clip-model.js`. That is a deliberate current boundary, but it means
  the clip model is not yet the only dataset path.
- `studio-lut-webgl.js` owns a global renderer boundary through
  `window.OrgaLutPreview`.
- The entry overrides `window.fetch` to attach Studio history group headers.
  This is intentional but global.

## 3. Dependency overview

Current internal ES-module imports:

```text
studio.js
  -> studio-lut-webgl.js (side effect)
  -> studio/export.js
  -> studio/format.js
  -> studio/project-browser.js
  -> studio/inspector/detail.js
  -> studio/clip-model.js
  -> studio/proxy-policy.js

studio/export.js -> studio/format.js
studio/inspector/detail.js -> studio/settings.js
studio/clip-model.js -> (none)
studio/format.js -> (none)
studio/project-browser.js -> (none)
studio/proxy-policy.js -> (none)
studio/settings.js -> (none)
```

- Circular imports: **none detected**.
- Modules importing the entry: **none**.
- Feature-to-feature imports: only `inspector/detail.js -> settings.js`, which is
  a core dependency, not another feature module.
- Hidden global surface: `window.OrgaLutPreview` (WebGL renderer) and the entry's
  `window.fetch` wrapper. No new `window.OrgaStudio*` objects.

The dependency diagram in `docs/STUDIO_MODULES.md` remains the target shape.
The current tree has fewer internal imports than that target diagram.

## 4. State and persistence flow

1. **Where is clip state?** The DOM dataset is authoritative. `clip-model.js`
   reads it and exposes one narrow writer. There is no shadow copy of clip state.
2. **Who may change dataset fields?** `clip-model.setClipField` for supported
   fields; legacy entry functions and `inspector/detail.js` still write selected
   fields directly.
3. **Who decides when to save?** `settings.js` for the Detail chain; the entry for
   all other chains. The entry still has eight save chains and thirteen `save*`
   functions with repeated timer/chain/refresh logic.
4. **Who triggers preview updates?** The entry. `inspector/detail.js` gets panel
   refresh through `fill` and save-state through `setSaved`; it does not own
   preview rendering.
5. **Who decides proxy/WebGL behavior?** `proxy-policy.js` supplies the pure
   eligibility/WebGL/key rules. The entry still reads clip state, schedules
   renders, fetches, caches, and updates UI chips. `studio-lut-webgl.js` owns the
   renderer global.
6. **Can multiple modules change the same setting?** In the current tree, Detail
   has one owner. Other settings still have entry-level writers. The risk is a
   future module writing a dataset field without using the same save/refresh
   path.
7. **Double saves or extra proxy renders?** No known duplicate Detail save path:
   `inspector/detail.js` binds once and uses one `settings.js` saver. Proxy
   scheduling already coalesces in-flight work in the entry. The broader risk is
   the remaining repeated save chains, not a present duplicate in Detail.

## 5. Risks

| Risk | Severity | Evidence |
|---|---|---|
| Monolithic entry remains the main change surface | High | 11,399 lines, 466 functions, 732 `.dataset.*` references |
| Repeated save chains | High | 8 chains, 13 `save*` functions, duplicated timer/error/refresh patterns |
| Text-slicing JS tests | High | 9 `.cjs` harnesses read `studio.js` and slice source text |
| Clip dataset writes are not yet centralized | Medium | `detail.js` writes `dataset.detail`; entry writes many fields |
| Global renderer boundary | Medium | `studio-lut-webgl.js` sets `window.OrgaLutPreview` |
| Entry patches global fetch | Medium | History group header logic in `studio.js` |
| Large templates and styles | Medium | `studio.html` ~1.6k lines, `app.css` ~4.7k lines |

## 6. Existing test coverage

Direct module tests:

- `clip_model.test.js`: identity, type, durations, fallbacks, writes, pure reads,
  no network calls.
- `settings.test.js`: serialization, error continuation, debounce, flush, missing
  payload, `apply` cancellation.
- `inspector_detail.test.js`: clamps, read/write, fill, input/change/reset,
  save failure, listener lifecycle.
- `proxy_policy.test.js`: eligibility truth table, WebGL fallback, cache-key
  shape.
- `export_ui.test.js`: export dialog, polling, cancel, success, errors, retries.
- `project_browser.test.js`: create/open/rename/delete, prompts, errors.
- `format.test.js`: time, lane time, template, export-clock formatting.

Indirect browser-logic harnesses run from Python:

- `color_playback_proxy.cjs`, `color_wheels.cjs`, `hsl_preview.cjs`,
  `lut_preview.cjs`, `lut_proxy_audio.cjs`, `lut_proxy_auto_prepare.cjs`,
  `lut_proxy_mapping.cjs`, `lut_webgl_hsl_gate.cjs`, `wheels_preview.cjs`.

These `.cjs` harnesses still read and slice `studio.js`. They are valuable
regression checks for playback/proxy behavior, but they are brittle when the
entry changes. No direct module test currently covers the proxy scheduler itself;
`proxy_policy.test.js` covers only the pure policy rules.

Test gaps:

- No direct module tests for the remaining save chains.
- No direct test for the entry's proxy scheduling/coalescing lifecycle.
- Title-card and inspector wiring rely mainly on Python route/DOM tests.
- Preview/export parity remains covered by Python pixel/FFmpeg tests, not a
  browser driver.

## 7. Prioritized next refactorings

| Rank | Candidate | Benefit | Coupling reduction | Testability | Risk | Effort |
|---:|---|---|---|---|---|---|
| 1 | Migrate one existing save chain (Image) to `settings.js` | High | High | High | Medium | Medium |
| 2 | Extract Inspector Image or Color panel as next feature module | Medium | Medium | High | Medium | Medium |
| 3 | Replace one text-slicing harness with direct module/contract tests | Medium | Low | High | Low | Low |
| 4 | Extract preview/proxy scheduling with a dedicated regression plan | High | High | Medium | High | High |
| 5 | Extract Timeline layout/selection with DOM fixtures | Medium | Medium | Medium | High | High |

Do not start with Timeline or Playback. They are central, stateful, and covered
mostly by indirect tests. The next useful step is to reduce duplicated save logic
and make one more setting path directly testable.

## 8. Recommendation for PR 9

**PR 9 should migrate exactly one existing save chain to `settings.js` — preferably
the Image adjust chain.** Keep the existing URL, PATCH shape, debounce behavior,
error copy, preview refresh, and save-state transitions unchanged. Add direct
Node tests for that chain before removing the entry-local timer/chain code.

Reasons:

- The Detail chain already proves the scheduler pattern.
- Image adjust is a bounded panel with existing Python coverage.
- It reduces a real duplicate save chain without touching playback, proxy, or
  export.
- It creates a reusable test model for HSL, wheels, masks, overlays, map, HUD,
  frame, and saturation ramp later.

Do not combine PR 9 with playback, proxy, timeline, or export changes.

## 9. Non-goals

- No new global state system or shadow clip store.
- No change to the DOM/dataset as the source of truth.
- No playback, audio-sync, proxy, cache, WebGL, LUT, or export pipeline rewrite.
- No SQLite or `effect_settings` schema change.
- No new framework, bundler, TypeScript migration, or mass formatting.
- No claim that target modules already exist when they do not.
- No additional refactoring PRs without approval.

## PR 8 small improvement

The only code improvement in PR 8 is removing the redundant
`formatExportDuration` re-export from `studio/export.js` and removing the
duplicate export-clock assertions from `export_ui.test.js`. The formatter remains
owned and directly tested in `studio/format.js`.

This is behavior-neutral: no runtime consumer imported the formatter through
`export.js`, and `format.test.js` already covers the formatter's values.

## Metrics

| Metric | Value |
|---|---:|
| `studio.js` lines | 11,399 |
| `studio.js` function declarations | 466 |
| Direct `.dataset.*` references in `studio.js` | 732 |
| Direct migrated clip-field dataset references | 269 |
| Extracted Studio ES modules | 7 |
| Direct Node module test files | 7 |
| Direct Node test cases | 43 |
| Python-run `.cjs` harnesses | 9 |
| Circular imports | 0 |
| New global interfaces | 0 |
