# ADR 0011: Studio per-clip image adjustment

- **Status:** Accepted
- **Date:** 2026-10-23
- **Deciders:** Issue #76

## Context

Overcast drone video often looks flat. Studio can already trim, order, transition,
add music, and export an MP4, but a hobbyist still needed another editor for a
small brightness or warmth change. ADR 0004 reserved `studio_clips.effect_settings`
for later media effects. ADR 0010 kept transitions out of that JSON.

## Decision

1. Store four integer sliders per Story clip in `effect_settings.image`:
   `exposure`, `contrast`, `saturation`, `warmth`. Each is -100…100. Missing,
   empty, or invalid JSON renders as 0. The same source added twice may differ.
   Photos and Title Cards do not accept these controls.
2. The server rejects non-numbers, booleans, non-finite values, and anything
   outside the slider range. Filter text is built only from formatted numbers.
3. Export prepends ffmpeg filters to the existing segment chain, before scale
   and fades: `colortemperature` (omitted at warmth 0), `exposure` (±1.0 EV at
   full scale), and `eq` contrast 0.5…1.5 / saturation 0…2. Neutral clips add
   no filters. Crossfade still blends finished segments; source audio and music
   are unchanged.
4. Preview uses CSS `brightness` / `contrast` / `saturate` plus an sRGB
   `feColorMatrix` for warmth. Brightness matches measured `exposure` multiplies.
   Warmth uses the same peak-normalized blackbody gains as ffmpeg 7.1
   `colortemperature`. Contrast and saturation match the numeric factors, not
   the YUV math. The preview is an approximation, not a pixel match.

## Alternatives considered

1. **New columns** — unnecessary; the reserved JSON object is the clip-instance
   store and old rows stay valid.
2. **CSS only, or a second renderer** — would drift from export or replace the
   current ffmpeg path.
3. **Pass 6500 K at neutral warmth** — ffmpeg’s 6500 K blackbody is not identity,
   so the filter is omitted instead.

## Consequences

- Positive: Existing projects and neutral exports keep today’s picture. Cuts copy
  the JSON onto the new clip. Fades still go to black.
- Negative / trade-offs: Preview and MP4 can disagree in color, especially
  contrast. This is not a LUT, curve, or D-Log workflow.
- Follow-up: photo correction, presets, and keyframes stay out of scope.
