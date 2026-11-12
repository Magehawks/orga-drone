# Discovery: Unified timed-effect Source/Story clocks (#331)

Status: **Discovery / decision proposal** — no behavior change in this document.
Unblocks #332 (bounded speed-ramp region). Product Owner decides before schema
or renderer changes.

## Problem

Each Studio timed effect currently owns ad-hoc clock rules inside
`effect_settings` (ADR 0034 ramps, color animation bars, framing, masks,
overlays). Independently editable, time-bounded regions are hard to compose
because Source vs Story clocks are special-cased per feature.

## Inventory (verified on develop)

| Feature | Clock | Bounds storage | Notes |
|---------|-------|----------------|-------|
| Speed ramp | Source | Absolute `source_s` points; bar may edge-trim | ADR 0034; whole-clip or edge-pinned 1× outside |
| Timelapse | Source (flat ramp) | Same as ramp | #325 / #333 |
| Color animation | Story (clip-local) | Effect-lane bar start/end + points | Absolute keyed values inside bar |
| Slow bar | Story/clip | Legacy | Replaced when ramp applies |
| Overlays | Story (clip-local) | `start_s`/`end_s` on overlay | Output clock |
| Masks / framing / HUD / map | Source | Source-timed | Follow remapped source under ramp |
| Music | Story (project) | Sequential + `music_start_s` | ADR 0008 / 0026 |
| SFX (PR #391) | Story (project) | `start_s` + source trim | ADR 0036 |

## Shared API proposal (no Big-Bang rewrite)

Introduce a **small pure module** (Python + JS twins) — not a generic NLE engine:

```text
ClipClocks
  sourceSpan(clip) -> { in, out }
  storySpan(clip, projectTiming) -> { start, end }   # after ramp/repeat/loop
  sourceToStory(clip, source_s) -> story_s
  storyToSource(clip, story_s) -> source_s
  regionToSource(clip, { start, end, clock }) -> { source_in, source_out }
  regionToStory(clip, { start, end, clock }) -> { story_in, story_out }
```

Rules:

1. **Persistence keys stay** until a separate ADR migrates them. The module
   *interprets* existing JSON; it does not invent a second bag.
2. Effects declare `clock: "source" | "story"` once (code constant today;
   optional JSON later).
3. Ramp / Timelapse remain the **only** timing remappers. Other source-clock
   effects sample through `storyToSource` after remapping.
4. Story-clock effects (overlays, color bars, SFX) never pass through the ramp
   integral; they use clip/project Story time as today.
5. One Effekt-lane bar per effect *kind* remains the default (#333 Option A /
   ADR 0034). Multiple regions for one kind (#332) are an explicit extension
   that stores a single bounded region first (`region_source_in` /
   `region_source_out` or edge-trimmed points with exterior 1× — prefer reusing
   ADR 0034 edge-pin semantics).

## #332 enablement (bounded ramp MVP)

Recommended contract for one bounded ramp region:

- Store the existing ADR 0034 point list **inside** the region only.
- Outside `[region_source_in, region_source_out]` play at 1× (same mental model
  as today's edge-trimmed ramp bar).
- Timeline handles move/resize the region; inspector edits curve points.
- Preview/export use the same `sourceToStory` / frame-grid path.
- No new SQLite table; optional explicit region keys only if edge-pin alone is
  insufficient — prefer edge-pin first to avoid schema churn.

## Migration path

1. Extract mapping helpers from `studio_speed_ramp.py` / `speed-ramp.js` and the
   JS Story layout into `studio_clocks.py` / `studio/clocks.js` (pure).
2. Call sites switch incrementally (ramp first, then color bar, then overlays).
3. #332 lands on the shared helpers with focused tests.
4. Multiple regions / composition rules stay Later (follow-up after #332 MVP).

## Non-goals

- Full keyframe NLE, Bézier editor, beat sync
- Schema churn without ADR
- Changing music sequential semantics
- Optical flow / interpolation

## Recommendation for PO

**Approve the shared ClipClocks helper extraction + #332 bounded region via
ADR 0034 edge-pin semantics** (no new persistence shape unless probes fail).
Defer multi-region composition until after #332 MVP ships.

**READY_FOR_PO_DECISION**
