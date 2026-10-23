# ADR 0017: Studio privacy masks

- **Status:** Accepted
- **Date:** 2026-10-23
- **Deciders:** Issue #81

## Context

Drone photos and videos can show people, plates, or house numbers. Title Cards
and image adjustment do not hide a region of an existing picture. ADR 0004
reserved `studio_clips.effect_settings` for clip effects. ADR 0011 stores image
sliders in that JSON under `image`.

## Decision

1. Store up to 8 rectangular masks per photo or video clip in
   `effect_settings.masks`. Each mask has an effect (`blur` or `pixelate`), a
   strength from 1 to 100, and a box in fractions of the fitted picture. The
   box is a region model so a later slice can add a time range. This slice
   covers the whole clip. Title Cards do not accept masks. Invalid stored
   entries are dropped. The same source added twice may differ.
2. Positions are clamped into the picture. Colors and text are not part of a
   mask. Filter text is built only from integers. A mask that cannot be placed
   fails the export with a clear error instead of omitting the mask.
3. Export runs the existing grade and scale/pad chain, then crops each region,
   blurs or pixelates it, and overlays it before fades. The stitch graph is
   unchanged, so a crossfade blends the already masked segment and the mask
   does not continue on the next clip. Neutral clips stay on the previous
   `-vf` path.
4. Coordinates use the fitted picture, so letterboxing and a different export
   resolution do not move the region. Blur radius and pixel-block size are
   fractions of the shorter fitted side. Preview draws the same fractions on
   the object-fit picture. It approximates ffmpeg `boxblur`; pixelate uses
   nearest-neighbor scaling on both sides.

## Alternatives considered

1. **Burn the mask into the library file** — conflicts with non-destructive
   Studio edits.
2. **A free mask track or tracker** — out of scope for this slice.
3. **CSS blur on a duplicated video element** — two decoders drift while
   seeking. A canvas sample of the visible frame stays on the playhead.

## Consequences

- Positive: Older projects stay valid. Cuts copy the JSON. Fades still reach
  black, including the mask. Music and source audio are unchanged.
- Negative / trade-offs: Masks do not follow a moving subject. Blur is not a
  legal anonymization guarantee. Preview and MP4 can disagree slightly in the
  blur kernel.
- Follow-up: time ranges, tracking, and freeform shapes stay out of scope.
