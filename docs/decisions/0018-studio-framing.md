# ADR 0018: Studio per-clip zoom and pan

- **Status:** Accepted
- **Date:** 2026-10-23
- **Deciders:** Issue #86

## Context

Timeline zoom only changes the Story canvas scale. Creators still needed another
editor to push in on a subject or reframe a photo or video inside a Story.
The existing export already fits each clip into the output frame and letterboxes
when the aspects differ. That fit at 1.0× has to stay unchanged.

## Decision

1. Store `effect_settings.frame` on photo and video clips: `zoom_start`,
   `zoom_end` (1.00–3.00) and focal points `x_start`, `y_start`, `x_end`,
   `y_end` (0–1 of the source picture, default center). Missing or invalid
   JSON is zoom 1 at the center. Title Cards are rejected. Cut copies the
   JSON onto both pieces. The source file is not modified.
2. Equal start and end values are a static crop. Different values interpolate
   linearly across the trimmed clip. There is no keyframe list.
3. Zoom 1 adds no filters, so the segment chain stays the existing fit.
   A static zoom crops a window inside the fitted picture (not the letterbox)
   and fits that window back into the frame. The window is clamped to the
   picture, so the crop does not reveal pixels outside the image. Motion uses
   `zoompan` on the source, then the existing scale/pad letterboxes that
   picture. Grade runs first. Fades run last. Crossfade still blends finished
   segments.
4. Video motion uses ffmpeg `time` minus the trim start because `-ss` is an
   output option. Progress is `(time - source_start) / duration`. Photo time
   starts at 0.
5. Preview uses the same window math with a CSS transform on the fitted
   picture. At 1× the transform is omitted. Dragging the preview moves the
   focal point of the active endpoint. Motion edits the end zoom and the end
   point; turning motion off copies the start onto the end.
6. Timed overlays and privacy masks composite after this crop and before fades
   so they stay anchored to the output frame instead of moving with the zoom.

## Alternatives considered

1. **ffmpeg `zoompan`** — stretches to fill and drops the current letterbox.
2. **Cropping the output frame, including bars** — enlarges the letterbox
   instead of the subject.
3. **A keyframe editor** — more than the start/end motion this slice needs.

## Consequences

- Older projects stay valid. Neutral clips keep the previous filter string.
- Preview and MP4 share one window calculation. Image-adjustment preview is
  still an approximation; framing is the fitted window, not a color match.
- This is not subject tracking, stabilization, or optical zoom.
