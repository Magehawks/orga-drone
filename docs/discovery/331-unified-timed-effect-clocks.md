# Discovery: Unified timed-effect clocks (#331)

Status: **Discovery complete — decision recorded in
[ADR 0037](../decisions/0037-studio-source-story-clocks.md) (Proposed).**  
No runtime behavior change in this issue. Product Owner acceptance of ADR 0037
unlocks [#332](https://github.com/Magehawks/orga-drone/issues/332).

Baseline: branch `docs/331-unified-clocks` from current `origin/develop`.

## Problem

Each Studio timed effect special-cases Source vs Story time. Composing
independently editable, time-bounded effects (starting with one bounded
speed-ramp region) needs a shared vocabulary without a Big-Bang rewrite or
generic NLE.

## Inventory (develop tip)

| Feature | Clock in practice | Key evidence |
|---------|-------------------|--------------|
| Speed ramp (ADR 0034) | Absolute file **Source** `source_s`; map + inverse to Story | `studio_speed_ramp.py`, `static/js/studio/speed-ramp.js` |
| Timelapse | Flat two-point ramp via same Source contract | `studio_timelapse.py` → `/speed-ramp` |
| Color animation | **Story-local** bar + keys from trimmed in-point | `studio_color_animation.py` (`bar_start_s` / keys); ramp path expands loops before color |
| Saturation ramp | **Story-local** `start_s`/`end_s` | ADR 0019, `studio_image.py` |
| Overlays | **Story-local** / output; after retiming on ramp export | ADR 0016; `studio_ramp_encoder.py` “Story overlays stay after retiming” |
| Masks / framing / zoom bar | **Source** offset from in-point | `studio_effect_lane.py`, `studio_mask.py`, ADR 0017/0018 |
| Slow bars | **Source** offset; outside = 1× | `studio_effect_lane.slow_bar` / `speed_at` |
| Section repeat | Source span × count → Story; overlays/framing follow plays | ADR 0021 |
| Forward loop | Derived Source plays to soundtrack Story length | `studio_forward_loop.py` |
| Detached clip audio | Source trim + Story-local `place_s`; muted under ramp | `studio_audio.py` |
| Project music | **Project Story** (+ lead-in) | ADR 0008 / 0026 |
| HUD / map | **Source** | ADR 0022 / 0023; `sourceClock` in `studio.js` |

SFX / ADR 0036 are **not** present on this develop tip; if a later merge adds
project-Story SFX, bind them like music (Project Story), not Source.

Edge-trim on the ramp bar already pins endpoint speeds to 1× when the active
Source span is shorter than the playable window (`remapRampSpan` in
`speed-ramp.js`) — the Slow-bar mental model ADR 0034 describes.

## Recommendation

Adopt ADR 0037:

1. Name three clocks only: Source, Story-local, Project Story.
2. Bind each effect family once (table in the ADR); keep existing persistence
   keys until a later ADR migrates them.
3. Extract the smallest shared pure map helpers over time (Python/JS twins
   beside `studio_speed_ramp` / `speed-ramp.js`), not a new engine. Illustrative
   surface from the ADR: playable Source span, Story duration, Source↔Story-local
   maps, and per-family clock ownership.
4. For #332: one Source-bounded ramp region, outside = 1×, inside = existing
   curve, still stored as `speed_ramp` (prefer formalizing edge-pin first).

Rejected: Story-local-only ramp bounds; Big-Bang envelope; multi-region or
Timelapse coexistence in the same slice (see
`timelapse-ramp-coexistence-discovery.md` Option B — depends on this ADR + #332).

## PO engineering criteria (docs-only issue)

| Criterion | Applicability |
|-----------|---------------|
| Isolated worktree / PR to `develop` | Applies — this branch |
| Modularity / reuse / existing UI | N/A for docs; ADR constrains #332 to existing ramp modules and Effect lane |
| Shared API / MCP | N/A here; #332 should reuse `/speed-ramp` (or existing shared action) and document NOT_APPLICABLE rather than invent endpoints |
| E2E | N/A for documentation; #332 owns mapping + preview/export evidence |

## Outcome for #332

After PO accepts ADR 0037, #332 can proceed. It does not need further clock
discovery beyond implementing the Source-region contract above.
