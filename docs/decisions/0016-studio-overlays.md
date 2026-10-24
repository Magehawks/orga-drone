# ADR 0016: Studio timed overlays

- **Status:** Accepted
- **Date:** 2026-10-23
- **Deciders:** Issue #78

## Context

Title Cards are separate Story items. They do not place a label, arrow, or
small image on an existing photo or video. ADR 0004 reserved
`studio_clips.effect_settings` for clip effects. ADR 0011 stores image sliders
in that JSON under `image`.

## Decision

1. Store up to 8 overlays per photo or video clip in `effect_settings.overlays`.
   Each has a kind (`text`, `arrow`, `circle`, `rectangle`, `image`), a
   clip-relative start and end, and a box in fractions of the fitted picture.
   Title Cards do not accept overlays. Missing or invalid stored entries are
   dropped. The same source added twice may differ.
2. Times that fall outside the clip are clamped. Positions, colors, and asset
   names are validated. Filter text is built only from formatted numbers.
   User text is drawn with Pillow, not interpolated into FFmpeg.
3. Image overlays are re-encoded PNG or JPEG files under the app data
   directory. The original path is not stored. A missing file fails the export
   with a clear error.
4. Coordinates use the fitted picture inside the export frame, so letterboxing
   does not move an overlay. Export draws a transparent PNG and composites it
   in the existing segment, after scale and before fades. The stitch graph is
   unchanged. During a crossfade the overlay is already part of its own
   segment, so it blends with that clip and does not continue on the next one.
   Video filter time follows the source timestamp because `-ss` stays an
   output option; enable windows shift by the trim in-point.
5. Optional animation is one preset: none, fade in, fade out, or slide in from
   a fixed side. Duration is 0.1–2.0 s and cannot exceed the overlay interval.
   Preview uses the playhead time, so seeking does not restart a CSS animation.

## Alternatives considered

1. **A free overlay track** — a second timeline, which this issue excludes.
2. **drawtext with user strings** — filter injection and font escaping.
3. **Burn overlays after the stitch** — they could leak across a crossfade.

## Consequences

- Positive: Older projects stay unchanged. Cuts copy the JSON. Fades still
  reach black, including the overlay. Music and source audio are untouched.
- Negative / trade-offs: Preview and MP4 can disagree slightly in font and
  stroke. This is not a keyframe or tracking tool.
- Follow-up: motion paths, masks, and rich text stay out of scope.
