# ADR 0029: Studio HSL colour mixer as a generated 3D LUT

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** Engineering (Issue #232)

## Context

Issue #232 asks for eight smooth HSL ranges (red, orange, yellow, green, aqua,
blue, purple, magenta), each with Hue, Saturation, and Luminance. Preview stills,
optional playback proxies, and MP4 export already share the `studio_image` grade
and `studio_lut` filter builders (ADR 0028). CSS cannot express hue-selective
adjustments, and a second WebGL/Canvas grading engine is explicitly out of
scope.

FFmpeg 7.1 ships `huesaturation`, but it exposes only six fixed colour buckets
and cannot carry eight independent ranges or a documented smooth hue boundary.

## Decision

1. Store HSL settings in `studio_clips.effect_settings` under `hsl.ranges`.
   Missing or invalid data is neutral. No schema migration is needed.
2. Generate a deterministic 33³ `.cube` LUT from the eight sliders and apply it
   with FFmpeg `lut3d` (`interp=tetrahedral`).
3. Use one documented order for pause/scrub stills, playback proxies, and MP4
   export: **grade → conversion/creative LUTs → HSL → detail → saturation ramp**.
   The HSL stage is a separate `lut3d` after user LUTs, so nothing is disabled
   and no stage runs twice.
4. Hue weighting uses smoothstep crossfades between range centres at 0, 30, 60,
   120, 180, 240, 270, and 300 degrees. A near-gray chroma gate prevents tinting
   pixels whose hue is undefined.
5. Internal mappings: ±45° hue at full slider, 0×–2× saturation, ±0.30 HSL
   lightness. UI values stay -100…100.
6. Cache generated cubes under `{data_dir}/hsl-luts/`, cap the folder at 64 MB,
   and include it in Settings' rebuildable cache clear.
7. Playback follows the existing LUT honesty rule: pause/scrub shows a rendered
   still from the shared builders; live playback may omit HSL and displays a
   state chip. The optional playback proxy now accepts HSL clips and uses the
   same chain.

## Alternatives considered

1. WebGL/Canvas HSL shader — second pixel engine; rejected.
2. FFmpeg `huesaturation` — six buckets, no independent eight-range model, no
   documented smooth boundary.
3. Per-pixel Python rendering for every preview — too slow and not the shared
   export path.

## Consequences

- Positive: one deterministic implementation for stills, proxy, and export;
  smooth ranges; old projects load unchanged.
- Negative: 33³ cube generation costs roughly 0.2 s per new slider state and
  the cache is disk-backed. Live playback without the optional proxy cannot
  show HSL; the existing state chip states that honestly.
- Out of scope: colour wheels, curves, sky masks, AI masking, new player engine.
