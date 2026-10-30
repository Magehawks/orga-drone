# ADR 0028: Studio LUT preview via shared FFmpeg stills

- **Status:** Accepted
- **Date:** 2026-10-30
- **Deciders:** Engineering (CTO gate for #211 PR1)

## Context

ADR 0027 §7 stated that Studio preview approximates grade sliders only and that
LUT application is export-truth. CSS and SVG cannot apply user `.cube` files.
Discovery #172 and #189 require either server stills, a second pixel engine, or
honest “LUT on export only” copy. Issue #211 needs pause/scrub LUT visibility
before animated creative strength can ship. A second WebGL/CSS LUT engine is
rejected.

## Decision

1. Add a local still path that builds **one FFmpeg graph** per request using the
   same `ffmpeg_grade_chain` and `ffmpeg_lut_chain` builders as Studio MP4
   export (grade → LUT). Sharpen/denoise may be omitted for speed.
2. Serve JPEG stills from `GET /api/studio/{id}/preview-frame` for pause and
   scrub when a clip has a non-neutral color look. Longest edge ≤ 720. Cache
   under `{data_dir}/preview-stills/` (cleared with Settings cache clear).
3. **Playback** may keep live `<video>` + CSS grade **without** LUT, with an
   on-screen state chip. Do not claim live or 30 fps graded+LUT playback.
4. Amend ADR 0027 §7: pause/scrub stills are preview truth for LUT; playback
   may still approximate. Product honesty strings must match.
5. Cold scrub latency target ≤ ~1.0 s median on typical 4K with 720 proxy. If
   mitigations fail that budget, document infeasible — do not ship export-only
   animated LUT later (#211 PR3).
6. Limited color keyframe animation (`color_animation`) is a follow-up (#211
   PR2) on this still path; conversion LUT, sharpen/denoise, photos-as-NLE,
   and Bézier remain out of that slice.

## Alternatives considered

1. WebGL / Canvas `.cube` — second pixel engine; rejected by #172.
2. Export-only LUT forever — blocks #211 LUT animation honesty.
3. Full realtime graded+LUT playback — not feasible in WebView2 at drone 4K.

## Consequences

- Positive: LUT look visible on pause/scrub; shared filter builders with export.
- Negative / trade-offs: Scrub is quantized and cached; playback without LUT
  needs a clear badge; disk cache growth (capped + Settings clear).
- Follow-up: #211 PR2 color points; PR3 creative strength animation only after
  this scrub gate stays green.
