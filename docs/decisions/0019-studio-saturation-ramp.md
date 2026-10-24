# ADR 0019: Studio video saturation ramp

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** Issue #109

## Context

A static per-clip grade (ADR 0011) cannot change mood inside one drone shot.
Creators want the same clip to move from color toward black and white. A
general keyframe editor is a different product. Issue #109 asks for one linear
range, in preview and in the MP4, that leaves existing grades unchanged until
it is turned on.

## Decision

1. Store one ramp per video Story clip in `effect_settings.saturation_ramp`:
   `enabled`, `start_s`, `end_s`, `start_saturation`, `end_saturation`.
   Saturation is 0–100, where 100% keeps the current grade and 0% is black
   and white. Times are seconds into the trimmed clip. Missing or invalid
   JSON leaves the grade untouched. Photos and Title Cards reject the control.
2. The ramp multiplies the graded saturation. Brightness, contrast, warmth,
   and the static saturation slider still run first. Export appends an ffmpeg
   `hue` saturation expression built only from formatted numbers. Clip-relative
   time is filter `t` minus the trim in-point, because `-ss` stays an output
   option. A disabled ramp or a zero-length range adds no filter.
3. Preview uses the same 0–1 multiplier on CSS `saturate`, after the existing
   grade filters. Timing matches export. Color is still the ADR 0011
   approximation, not a pixel match.
4. Splitting a video keeps the left clip’s times and shifts the right clip’s
   times by the cut, so the picture is continuous. Other `effect_settings`
   keys are copied as before. Source files are never modified.

## Alternatives considered

1. **Animate the saturation slider with a keyframe list** — more than the
   two time points the issue asks for.
2. **Replace the grade’s saturation instead of multiplying it** — the static
   slider would disappear whenever the ramp is on.
3. **Store source-absolute times** — the Inspector speaks in clip time, and a
   split would still need a conversion. Clip-relative times plus a shift on
   the right piece keep Cut’s copy of every other effect.

## Consequences

- Positive: Existing projects stay unchanged until the ramp is enabled. The
  grade and the ramp compose in one order in preview and export.
- Negative / trade-offs: One range per clip. Preview and MP4 can still
  disagree in color the same way the static grade can. This is not a LUT or
  a keyframe editor.
- Follow-up: further animated grade controls stay out of scope.
