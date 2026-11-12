# ADR 0037: Shared Studio Source and Story clocks

- **Status:** Accepted (Product Owner, 2026-11-12). Unlocks
  [#332](https://github.com/Magehawks/orga-drone/issues/332) bounded speed-ramp
  region implementation under this clock contract.
- **Date:** 2026-11-12
- **Deciders:** Product Owner, following discovery for
  [#331](https://github.com/Magehawks/orga-drone/issues/331)
- **Baseline:** `origin/develop` tip used by branch `docs/331-unified-clocks`
- **Related:** ADR 0034 (speed ramp), ADR 0016–0019, ADR 0021, ADR 0008/0026;
  discovery note [331-unified-timed-effect-clocks.md](../discovery/331-unified-timed-effect-clocks.md)

## Context

Studio timed effects each special-case Source versus Story time inside a flat
`effect_settings` bag. Remapping (ADR 0034) expands ramp passes before color;
Story overlays and fades stay on output clocks. Independently editable,
time-bounded effects are hard to compose without a shared vocabulary.

Issue #332 needs one independently bounded speed-ramp region (outside = 1×,
inside = existing curve) with timeline handles, persistence, preview/export
parity, and undo/reopen. That work must not invent a generic NLE engine or
churn SQLite schema. This ADR records the smallest shared clock decision that
unlocks #332 and guides later timed-effect work without a Big-Bang rewrite.

## Decision

### 1. Two clip clocks, plus project Story time

Studio keeps exactly these clocks. New timed features must declare which one
they bind to; they must not invent a third clip clock.

| Clock | Meaning | Typical unit |
|-------|---------|--------------|
| **Source** | Absolute seconds in the media file | `source_s` |
| **Story-local** | Seconds from the start of this clip's visible Story span (after trim, retiming, and repeat/loop expansion as applicable) | `local_s` / clip-relative |
| **Project Story** | Global playhead / soundtrack / ruler | `projectTimeS` / story start offsets |

Cut in/out (`source_start` / `source_end`) select the playable Source window.
They are not a separate clock. Photos and Title Cards use Story-local from 0
for their visible duration; they have no Source retiming map.

### 2. Ownership by effect family (inventory, binding)

This table is normative for new work. Persistence keys stay as today until a
later ADR migrates them.

| Family | Binding | Persistence (unchanged) | Notes |
|--------|---------|-------------------------|-------|
| Speed ramp / Timelapse flat ramp | **Source** (absolute `source_s` points) | `effect_settings.speed_ramp` | ADR 0034 map + inverse; Timelapse writes a flat two-point ramp through the same key |
| Legacy slow bar | **Source** offset from clip in-point | `effect_settings.slow_bar` (+ `playback_speed`) | Outside bar = 1×; inside = 0.5×/0.25×. Ramp replaces legacy slow for the whole clip when present |
| Framing / zoom bar | **Source** offset (progress across trimmed span) | `effect_settings.frame`, optional `zoom_bar` | Source effects precede retiming on the ramp export path |
| Privacy masks | **Source** offset when timed; whole clip when unset | `effect_settings.masks` | Timed `start_s`/`end_s` are Source-offset, not Story-local |
| Color animation | **Story-local** (trimmed in-point) | `effect_settings.color_animation` | Keys and bar relative to clip Story start; ramp path expands loops before color subdivision |
| Saturation ramp (legacy) | **Story-local** | `effect_settings.saturation_ramp` | Clip-relative; separate from color animation |
| Overlays + fades | **Story-local** / output | `effect_settings.overlays`, fade columns | After retiming on the ramp path; enable windows are clip-relative from visible t=0 |
| Section repeat | Source in/out × count → Story length | `effect_settings.section_repeats` | Framing/overlays follow one play and repeat; fades on first/last play |
| Forward loop to soundtrack | Derived Source plays → Story length | `loop_to_soundtrack`, join keys | Count derived from known soundtrack duration; not a second timing engine |
| Detached clip audio | Source in/out + Story-local `place_s` | `effect_settings.detached_audio` | Source muted for entire ramped clip (ADR 0034) |
| Project music | **Project Story** (+ `music_start_s`) | `studio_audio_clips`, project lead-in | Sequential playlist; stays on Story time under ramps |
| HUD / flight map | **Source** | `hud`, `map` + GPS track | Source clock so Cut does not restart telemetry |

### 3. Smallest shared API (library contract, not a new engine)

Introduce a thin, pure timing contract shared by Python and JavaScript twins.
Prefer extracting helpers beside existing modules
(`studio_speed_ramp.py` / `studio/speed-ramp.js`, `studio_estimate.py`,
`studio/format.js`) over a new framework.

Required operations (names illustrative):

1. `playable_source_span(clip) → (source_in_s, source_out_s)`
2. `story_duration_s(clip) → float` (existing estimate paths remain authoritative)
3. `source_to_story_local(clip, source_s) → local_s`
4. `story_local_to_source(clip, local_s) → source_s`
5. For ramped / slow-bar clips, (3)/(4) reuse the ADR 0034 map or the slow-bar
   piecewise map; for 1× clips they are identity within the playable span
6. `effect_clock(family) → "source" | "story_local" | "project_story"` from the
   ownership table above

Optional conceptual shape for timed regions (documentation and #332 UI math;
not a new persisted envelope yet):

```text
TimedRegion { clock: "source" | "story_local", start_s, end_s }
```

Rules:

- One region meaning per feature until a later ADR allows multiple.
- Overlap composition between different families stays feature-specific
  (current export order: Source effects → retiming → Story overlays/fades).
- No generic keyframe list, track graph, or plugin API.

### 4. Persistence and migration path (no Big Bang)

1. **Phase 0 (this ADR):** Document clocks and ownership. No code or schema
   change required to accept the decision.
2. **Phase 1 (#332):** Implement one bounded speed-ramp region using the
   existing `speed_ramp` key and Source clock. Do not add a parallel timing
   model or SQLite migration. Prefer formalizing the current edge-trim
   semantics (1× outside the active Source span; curve inside) with explicit
   tests and timeline handles. An optional nested `region` object inside
   `speed_ramp` is allowed only if #332 cannot express bounds safely with
   points alone; any such field needs its own write validation and downgrade
   note, still without a SQLite migration.
3. **Phase 2 (later issues):** Extract shared helper modules incrementally;
   point new readers at them. Leave legacy keys in place. Migrate or rename
   keys only under a dedicated ADR.
4. Unrelated `effect_settings` keys must survive every save (existing rule).
5. Whole-JSON Story history snapshots remain the undo unit.

### 5. What #332 must take from this decision

#332 (one bounded ramp region) is authorized to proceed after PO acceptance of
this ADR, under these constraints:

1. **Clock:** Region start/end are **Source** seconds (absolute file time),
   consistent with ADR 0034 points.
2. **Semantics:** Outside the region playback is **1×**. Inside the region,
   use the existing `reciprocal_smoothstep` curve (2–5 points, validated
   speeds). Exactly **one** region per clip in MVP; multiple regions stay
   out of scope.
3. **Duration:** Story length uses the shared Source→Story map (flanking 1×
   Source spans + mapped interior). Preview and export must share that map.
4. **Persistence:** Keep writing `effect_settings.speed_ramp`. No new top-level
   effect key and no SQLite schema change in #332.
5. **Lane UX:** Handles edit the Source region; Inspector may show Source or
   Story-local readouts derived via the shared helpers, not a second stored
   clock.
6. **Audio:** Source audio remains muted for the whole ramped clip; soundtrack
   stays on Project Story time (ADR 0034 / 0008).
7. **Composition:** Source-bound masks/framing/color subdivision and
   Story-bound overlays/fades keep the ADR 0034 export order; #332 must not
   reorder that pipeline.
8. **Tests:** Mapping fixtures, trim/edge-resize, undo/redo/reopen, and
   preview/export duration parity for outside=1× / inside=curve.

#332 does **not** need: a generic effect engine, multi-region composition
rules, Timelapse coexistence redesign (#333), or Control API / MCP surface
beyond whatever shared speed-ramp action path already exists (document
NOT_APPLICABLE for unused PO integration bullets rather than inventing
endpoints).

## Alternatives considered

1. **Big-Bang unified effect envelope** — rewrite all timed keys into one
   schema. Rejected: high migration risk, blocks #332, violates small-slice
   rules.
2. **Story-local-only ramp bounds** — rejected: ADR 0034 points are Source-
   anchored so trim/cut retain absolute file times; Story-local bounds would
   duplicate and drift under retiming.
3. **Treat edge-trim as UI-only** — rejected: #332 requires persistence and
   export to use the same bounds as preview; the clock contract must be
   explicit.
4. **Generic NLE / multi-track engine** — out of product scope
   (`docs/PRODUCT_VISION.md`).

## Consequences

- Positive: #332 can ship a bounded region against a written Source/Story
  contract without waiting for a platform rewrite; later timed features reuse
  the same vocabulary; existing keys remain valid.
- Negative / trade-offs: Clock binding remains partly implied by feature code
  until Phase 2 extraction; slow-bar and speed-ramp remain separate Source
  retimers with replace semantics rather than one composed speed model.
- Follow-up: #332 implementation; optional helper extraction; Timelapse
  multi-region coexistence only after this contract is accepted and #332
  lands; any key rename requires a new ADR.
