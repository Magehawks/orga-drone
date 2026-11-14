# ADR 0038: Up to three speed-ramp regions per clip

- **Status:** Accepted for this implementation branch; subject to Product Owner merge.
- **Date:** 2026-11-14
- **Deciders:** Implementation of the approved multi-region speed-ramp task.
- **Amends:** ADR 0034 (persisted ramp document), ADR 0037 §5.2 (one region per clip).
- **Baseline:** `origin/develop` at `8532a3d`.

## Context

ADR 0034 stores one reciprocal-smoothstep curve in `effect_settings.speed_ramp`.
ADR 0037 allows one optional Source `region` so playback is 1× outside that span
and the curve inside it. A ramp with no region keeps the endpoint hold.
Creators need several separate curves on one video clip, for example slow–fast–slow,
then fast–slow–fast, with normal 1× playback everywhere else.

The existing encoder already evaluates one FFmpeg primitive (`ffmpeg_time`) and
the shared Source→Story map. Multiple regions do not need a new renderer, a
second timing engine, or a SQLite migration.

## Decision

`effect_settings.speed_ramp` gains a versioned document. The same key, the same
`PATCH /api/studio/{id}/speed-ramp` route, and the same Story history snapshot
remain the only write path. No Control API or MCP action is added.

### Version 1 (unchanged)

```json
{"v": 1, "interp": "reciprocal_smoothstep", "points": [], "region": {"start_s": 0, "end_s": 1}}
```

`region` stays optional. Missing `region` keeps the ADR 0034 endpoint hold.
Documents that already saved this shape load and render as they do today.
Timelapse still writes a flat two-point version-1 ramp with no region, and
still replaces an existing ramp only after the existing confirmation.

### Version 2 (multiple regions)

```json
{
  "v": 2,
  "interp": "reciprocal_smoothstep",
  "regions": [
    {
      "id": "r1",
      "start_s": 3,
      "end_s": 7,
      "points": [{"source_s": 3, "speed": 0.5}, {"source_s": 7, "speed": 4}]
    }
  ]
}
```

Rules:

- At most three regions. Each has a stable id (`^[A-Za-z][A-Za-z0-9_-]{0,31}$`).
- Bounds are absolute Source seconds. Each region has its own 2–5 points.
- Speeds stay on the shared 0.25×–20× contract from ADR 0034 / #325.
- Regions are stored sorted by `start_s`. Overlap is rejected. A shared
  boundary is allowed and belongs to the earlier region. Zero-length regions
  (shorter than 0.05 s) are rejected.
- A region must lie inside the media file (`0` … `duration_s`). Trim does not
  delete regions; the map integrates only the playable window, the same way
  version-1 points survive a trim.
- Outside every region, playback is 1×. Inside a region, the existing
  reciprocal-smoothstep integral applies. Story duration is the sum of the 1×
  gaps and each region's interior. The inverse stays a bounded bisection of
  that primitive. Preview (`speed-ramp.js`) and export (`ffmpeg_time`) use it.
- Deleting one region does not change the ids, bounds, or points of the others.
  Deleting the last region clears the ramp. "Remove ramp" still clears all of them.
- Adding a region to a version-1 bounded ramp rewrites that ramp as version 2.
  The original points and bounds are copied; a new id is assigned once and then
  stored. An unbounded version-1 ramp is not converted, so its endpoint hold
  does not silently become 1× outside the points.

Older builds that only accept `v: 1` treat a version-2 document as malformed and
fall back to legacy timing, which is the ADR 0034 downgrade. They cannot
reproduce multiple regions.

## Consequences

Source masks, framing, color, HUD, and the flight map stay on the Source clock.
Story overlays and fades stay on the Story clock. Section repeats and forward
loops still expand passes from `duration` and `source_at`. Source audio stays
muted for the whole ramped clip. The export order does not change.

The inspector can add, select, and remove a region. A new region is placed in
the open tail after the last region when that tail can hold the preset span.
Otherwise it uses the widest gap that can hold the span, so a short hole before
the first region does not trap it. The effect lane draws one bar per region on
the same row. Arrow keys and edge drags edit the selected region and stop at
the neighboring region so the saved document cannot overlap.
