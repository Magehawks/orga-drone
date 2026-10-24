# ADR 0019: Studio video section repeat

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** Issue #112

## Context

Short-form drone stories often need one maneuver to play again, a few times,
inside the same Story. Duplicating clips by hand is easy to mis-align. Slow
motion is a separate request (Issue #111) and is not part of this slice.
Source files stay untouched. The existing Cut model already stores an in/out
range on `studio_clips`.

## Decision

1. The user sets source in, source out, and a whole-number repeat count on a
   video clip. 1 plays the range once. Counts above 8 are stored as 8. The
   count lives in `effect_settings.section_repeats` and is omitted at 1, so
   ordinary clips stay unchanged. A range that covers the whole media file is
   stored as NULL in/out, the same as Cut.
2. Story duration is `(out - in) × repeats`. Preview seeks back to the in
   point at each out point until the count is done. MP4 export encodes that
   same span once per play and joins the plays with a cut. Playback speed is
   unchanged. There is no `setpts` or `playback_speed` change.
3. Framing and overlays follow one play of the section and repeat with it.
   Fades stay on the first and last play. Cut in the Story toolbar stays
   available when the count is 1. While the count is above 1, Cut is disabled
   so a playhead in a later play is not treated as a second source split.
4. Photos, Title Cards, infinite loops, seamless crossfaded loops, reverse
   playback, and GIF export are out of scope.

## Alternatives considered

1. **Insert N duplicate Story rows** — matches “ordinary timeline items” but
   makes one repeat control harder to edit, and reorder can separate the
   copies. A count on the existing in/out range is the smaller slice.
2. **Change `playback_speed`** — that is slow motion, which this issue does
   not include.

## Consequences

- Positive: Non-destructive; story length, preview, and export share one
  count; existing one-play clips are unchanged.
- Negative / trade-offs: Repeats are not separate rows, so deleting one play
  means lowering the count. Preview seeks at the out point; export uses the
  full span. Joins are hard cuts, not blended loops.
