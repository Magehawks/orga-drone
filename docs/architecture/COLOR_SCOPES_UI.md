# Color Scopes UI (#362)

Status: **UI + managed-preview live tap for managed-sdr-v1 grades.**
Producer: [`COLOR_SCOPES_TAP.md`](COLOR_SCOPES_TAP.md) (`managed-preview-frame-v1`).
Owners: Cursor (UI) + engine tap (#366). Capture plane: [#359](https://github.com/Magehawks/orga-drone/issues/359)
preview-frame. Contract: [ADR 0035](../decisions/0035-color-workspace-contract.md),
[COLOR_WORKSPACE_CONTRACT.md](COLOR_WORKSPACE_CONTRACT.md) § Scope tap.

## Modules

| Module | Role |
| --- | --- |
| `static/js/studio/scopes/scope-frame.js` | Immutable `ScopeFrameV1`, identity, stale checks |
| `static/js/studio/scopes/accumulate.js` | Histogram / waveform / parade / vectorscope math |
| `static/js/studio/scopes/fixtures.js` | Deterministic synthetic frames |
| `static/js/studio/scopes/render.js` | Canvas painting (display only) |
| `static/js/studio/scopes/panel.js` | Pro inspector panel; fixture disclosure; metrics |
| `static/js/studio/scopes/engine-tap.js` | Capability probe + tagged-frame builder + controller (#366) |
| `static/js/studio/scopes/preview-tap.js` | Managed preview-frame producer (`managed-preview-frame-v1`) |
| `static/js/studio/scopes/index.js` | Public exports |

`studio.js` mounts the panel, controller, and managed preview producer. Scope
math stays in `studio/scopes/`.

## Honesty rule

Synthetic fixtures must never be labeled as live media measurements. An
explicit **Show test pattern** control enables fixtures and labels them as
test patterns. Live measurements require a tagged managed-preview engine tap.

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

`createScopeTapController` may call `colorScopes.injectFrame(frame)` only after
a capability probe reports a tagged engine source. Display blit / CSS /
undeclared JPEG / untagged WebGL candidates remain refused. The managed producer
publishes tagged frames from `/preview-frame`. See
[`COLOR_SCOPES_TAP.md`](COLOR_SCOPES_TAP.md).

### #359 (render adapters)

Scopes never mutate the render plan. Managed grades reuse the #359 preview-frame
path as the tagged post-grade/pre-frame plane. Playback refresh is rate-limited;
export filters are unchanged.

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
WebView2 live-tap latency/memory remain **NOT_RUN** until packaged evidence
is attached.

## Evidence matrix

| Check | Result |
| --- | --- |
| Unit math vs black/gray/RGB/color-bar fixtures | PASS (see `tests/js/scopes_*.test.js`) |
| Stale frame rejection | PASS |
| Panel does not call save APIs | PASS |
| Creative hides scopes; Pro shows section | PASS (CSS/template tests) |
| Windows WebView2 fixture UI journey | PASS (`packaging/e2e/studio_color_scopes.py`) |
| Managed preview producer + capability gating | PASS (`tests/js/scopes_preview_tap.test.js`) |
| Live media scope accuracy (packaged WebView2) | NOT_RUN — pending packaged E2E evidence |
| Engine-tap capability refusal of blit/CSS/JPEG | PASS (`tests/js/scopes_engine_tap.test.js`) |
| Packaged MOTW E2E | NOT_RUN — not in scope |

## Screenshots

Generated fixture previews: `docs/architecture/assets/scopes/`.
