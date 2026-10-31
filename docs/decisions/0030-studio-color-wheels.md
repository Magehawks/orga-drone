# ADR 0030: Studio colour wheels as a generated 3D LUT

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** Engineering (Issue #232 follow-up)

## Context

Issue #232 added an eight-range HSL mixer as a generated LUT after the user
LUTs. The follow-up asks for three interactive colour wheels for shadows,
midtones, and highlights. They must combine with HSL, Looks, LUTs, and global
image adjustments, persist per clip, and stay consistent between pause/scrub
stills, the optional playback proxy, and MP4 export.

A second pixel engine or a new playback architecture is out of scope.

## Decision

1. Store each wheel point in the unit disc under
   `studio_clips.effect_settings` → `color_wheels.wheels`. Missing or invalid
   data is neutral. No schema migration is needed.
2. Generate a deterministic 33³ `.cube` from the three points and apply it with
   FFmpeg `lut3d` (`interp=tetrahedral`), exactly like the HSL mixer.
3. Use one order everywhere: **grade → user LUTs → HSL → colour wheels → detail
   → saturation ramp**. HSL and the wheels are independent stages; either can
   be neutral without disabling the other.
4. Tonal weighting crossfades with smoothstep between shadow (luma 0), midtone
   (luma 0.5), and highlight (luma 1) centres. The three weights sum to 1.
5. A wheel tint is a zero-luma RGB direction. The point angle selects the hue
   and the radius selects intensity; full radius adds at most 0.20 per channel.
   The centre is exactly neutral.
6. Cache cubes under `{data_dir}/color-wheel-luts/`, cap the folder at 64 MB,
   and include it in Settings' rebuildable cache clear.
7. The UI adds an open, collapsible "Color Grading" section under the Image tab
   with three draggable wheels, a visible marker, per-wheel reset, pointer
   capture, and keyboard nudge (Shift for finer steps).

## Alternatives considered

1. WebGL/Canvas wheel shader — second pixel engine; rejected.
2. Lift/gamma/gain filter chain — does not expose a two-dimensional wheel point
   or a shared preview/export implementation as cleanly.
3. Reusing the HSL cube for the wheels — couples two independent models and
   makes cache invalidation and reset behaviour less obvious.

## Consequences

- Positive: one deterministic implementation for stills, proxy, and export;
  smooth tonal transitions; independent wheels; old projects load neutral.
- Negative: an additional generated LUT (roughly 0.2 s per new state) and a
  second `lut3d` stage when both HSL and wheels are active.
- Live playback still follows the existing LUT honesty rule: pause/scrub shows
  a rendered still; playback may omit the generated grades and says so.
- Out of scope: sky masks, AI grading, RGB curves, glow/bloom, new player.
