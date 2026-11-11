# Color Scopes UI (#362)

Status: **UI against fixtures.** Not a shipping live media scope.
Owners: Cursor (this UI). Engine tap: [#366](https://github.com/Magehawks/orga-drone/issues/366).
Render integration: [#359](https://github.com/Magehawks/orga-drone/issues/359).
Contract: [ADR 0035](../decisions/0035-color-workspace-contract.md),
[COLOR_WORKSPACE_CONTRACT.md](COLOR_WORKSPACE_CONTRACT.md) § Scope tap.

## Modules

| Module | Role |
| --- | --- |
| `static/js/studio/scopes/scope-frame.js` | Immutable `ScopeFrameV1`, identity, stale checks |
| `static/js/studio/scopes/accumulate.js` | Histogram / waveform / parade / vectorscope math |
| `static/js/studio/scopes/fixtures.js` | Deterministic synthetic frames |
| `static/js/studio/scopes/render.js` | Canvas painting (display only) |
| `static/js/studio/scopes/panel.js` | Pro inspector panel; fixture disclosure; metrics |
| `static/js/studio/scopes/index.js` | Public exports |

`studio.js` only mounts `createColorScopesPanel`. Scope math does not grow the entry.

## Honesty rule

Without the approved engine tap (#366), the UI **must not** present synthetic
values as a measurement of the user's media. Default state waits for a live tap.
An explicit **Show test pattern** control enables fixtures and labels them as
test patterns.

## ScopeFrameV1 (UI-consumed)

Fields follow ADR 0035: RGB buffer (BT.709 encoded [0,1] RGBA), dimensions/stride,
profile/transfer, straight alpha, PTS/frame index, project/clip/grade revision/
context digest, tap ID, ROI, sample factor, `sourceKind` (`fixture` | `engine-tap`).

Validation (UI gate before display):

- Dimensions, ROI, stride, `frameIndex`, and PTS use safe-integer checks (no
  bitwise `|0` truncation).
- `ptsDen` must be a positive safe integer; `profile`/`transfer` must be `bt709`.
- `rgb` is a defensive `Float32Array` copy. The frame object and ROI are frozen;
  TypedArray element slots cannot be deeply frozen in JS — callers must treat
  `rgb` as read-only.

View binding: `panel.syncView()` / `invalidate()` clears live measurements when
project, clip, grade revision, or context digest changes so a previous clip
cannot remain on screen. Studio calls this from selection and grade-summary
refresh. Fixture mode stays disclosed as a test pattern across clip switches.

Math (reference):

- Histogram: 256 bins, `min(255, floor(256*c))`; luma `Y'=0.2126R'+0.7152G'+0.0722B'`
- Waveform: x = normalized source x; y = Y'
- RGB parade: same x; separate R'/G'/B' panels
- Vectorscope: `Cb=(B'-Y')/1.8556`, `Cr=(R'-Y')/1.5748`, axes [-0.5, 0.5], Cb right, Cr up

## Integration points

### #366 (engine ScopeFrameV1 tap)

Codex owns producing immutable frames from graded pixels. When ready, Studio
preview/render orchestration calls `colorScopes.injectFrame(frame)`. The panel
rejects mismatched project/clip/revision/context and older frame indices, and
counts dropped frames while busy.

### #359 (render adapters)

Scopes never mutate the render plan. Adapter/cache work stays in #359. This UI
reads frames only; it does not request stills per playback tick and does not
add export filters.

## API / MCP / Actions

| Surface | Impact |
| --- | --- |
| Public HTTP API | **None.** No new endpoints. |
| Domain actions | **None.** Scopes do not write grades. |
| Control API / MCP | **None** in this PR. Future exposure would negotiate a read-only capability after #366; no duplicate grading engine. |
| Persistence / export | **Unchanged.** Toggles do not PATCH image/look/HSL/wheels. |

## Performance notes

`panel.getMetrics()` reports `lastProcessMs`, `acceptedFrames`, and
`droppedFrames`. Fixture and inject paths are measured in unit tests; Windows
WebView2 cost against live taps is **NOT_RUN** until #366 supplies frames.

## Evidence matrix

| Check | Result |
| --- | --- |
| Unit math vs black/gray/RGB/color-bar fixtures | PASS (see `tests/js/scopes_*.test.js`) |
| Stale frame rejection | PASS |
| Panel does not call save APIs | PASS |
| Creative hides scopes; Pro shows section | PASS (CSS/template tests) |
| Windows WebView2 fixture UI journey | PASS or NOT_RUN (packaging script; requires local WebView2) |
| Live media scope accuracy | NOT_RUN — blocked on #366 / #359 |
| Packaged MOTW E2E | NOT_RUN — not in scope |

## Screenshots

Generated fixture previews: `docs/architecture/assets/scopes/`.
