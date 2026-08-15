# ADR 0010: Studio visual transitions

- **Status:** Proposed
- **Date:** 2026-08-15
- **Deciders:** Issue #27

## Context

Studio already showed transition chips and an inspector, but choices lived in
`sessionStorage` and were not rendered. ADR 0004 reserved `studio_clips.transition`
as unused TEXT. Hard cuts between videos, photos, and Title Cards make a
finished memory feel abrupt. Fade-through-black and crossfade have different
timing: one is sequential, the other overlaps and shortens the Story.

## Decision

1. Persist canonical type ids (`cut`, `fade_black`, `crossfade`) in
   `studio_clips.transition` and a remembered duration in
   `studio_clips.transition_duration_s`. The outgoing clip owns the boundary.
   NULL / unknown / stub ids (`none`, `fade`, `slide`) resolve to Cut. Never
   store ffmpeg strings or `effect_settings`.
2. Shared math in `studio_transition.py` is used by estimate, preview playhead,
   export, and music trim. Crossfade subtracts overlap `D` from Story length.
   Fade-through-black does not (D/2 out + D/2 in, no extra black hold).
3. Applied `D` must leave ≥0.1 s of each neighbor outside the effect; otherwise
   clamp or fall back to Cut. Export never crashes.
4. Export bakes fade-through-black with ffmpeg `fade=` on segments then concat.
   Crossfade uses `xfade=transition=fade` only. Source audio hard-cuts (midpoint
   of a crossfade overlap; clip edge otherwise). Music is not faded by this
   feature.
5. Preview uses stacked layers / CSS opacity and a black overlay. It is close
   enough to judge type and duration, not pixel-identical to export.

## Alternatives considered

1. **`xfade=fadeblack` for both labeled effects** — would overlap and shorten
   fade-through-black, violating the product timing.
2. **JSON in `effect_settings`** — reserved for later media effects (ADR 0009).
3. **Keep sessionStorage** — not per-project and does not survive restart.

## Consequences

- Positive: Existing Cut-only projects keep today’s duration and pictures until
  a boundary is changed. Title Card boundaries are first-class.
- Negative / trade-offs: HTML preview can fall back to a still + incoming video
  for heavy dual-decode. `xfade` stitch is an extra re-encode when any
  crossfade is applied.
- Follow-up: wipes, audio crossfades, and easing stay Later.
