# ADR 0022: Studio telemetry HUD

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** Issue #107

## Context

DJI FPV pilots sometimes want speed, altitude, and elapsed time on the clean
video. Orga Drone already indexes a sibling SRT for the map. The parser in
`parse_srt` records cue time, latitude, longitude, `rel_alt`, and `abs_alt`.
It does not record speed, a home point, heading, battery, signal, or flight
mode.

The repository has no real Avata 2 recording. The fixture
`tests/fixtures/dji_srt_hud_sample.srt` uses the cue text that parser already
accepts: a frame line plus `[latitude] [longitude]` and, when present,
`[rel_alt abs_alt]`. Avata 2 is the intended aircraft when its sidecar uses
that DJI SRT shape. A cue without a GPS fix is ignored, because that is what
the existing parser does. GPS near 0,0 is ignored for the same reason.

## Decision

1. Store one boolean, `effect_settings.hud.enabled`, on a video Story clip.
   Photos and Title Cards do not accept it. The preset is off until the user
   turns it on, and it turns on only when the sibling `.SRT` or `.srt` yields
   at least one timed cue. Invalid JSON stays off. The source file is not
   modified.
2. The Inspector states availability per field. Elapsed time is available when
   a timed cue exists. Altitude is available when any cue has `rel_alt`.
   Speed and home distance are always unavailable: they are not in the parser,
   and this slice does not derive them. Missing altitude inside a clip is left
   blank. It is not replaced with a guessed number or the word unavailable on
   the picture.
3. Elapsed time is the source clock as `HH:MM:SS`. A Cut keeps that clock, so
   a clip that starts at 12 s does not restart at 00:00:00. Altitude uses the
   nearest `rel_alt` when it is within 1.0 s. Samples farther away are a gap.
   Preview and MP4 share 0.5 s windows built from those cues. During a
   crossfade the MP4 already has each segment's HUD burned in; the preview
   shows both clips' readouts and fades the incoming one with that clip.
4. Export draws the readout with `drawtext` on the framed picture, before
   fades, and only when the preset is on. A neutral clip keeps the previous
   filter chain. The typeface follows the Title Card font. Placement is the
   top-left of the frame. Preview uses the same text and a similar box; the
   typeface metrics can differ.

## Alternatives considered

1. **Derive speed from GPS deltas and treat the first fix as home** — those
   values are not in the recording. A noisy fix would look like an instrument.
2. **A DJI Goggles picture, several presets, or a HUD designer** — out of scope.
3. **Reuse the 200-point map track** — downsampling would look like missing
   telemetry. The HUD reads the SRT cues directly.

## Consequences

- Positive: Older projects stay valid. Cuts copy the JSON. The map track is
  unchanged. Fields the parser cannot read are visible as unavailable instead
  of being invented.
- Negative / trade-offs: Altitude can move up to half a second later than the
  cue, and it disappears when the nearest cue is more than one second away.
  Preview and MP4 can differ slightly in font and in how a crossfade composites
  the two readouts. This is not a legal flight instrument.
- Follow-up: speed, home distance, and heading stay out until a parser records
  them. Battery, signal, latency, and flight mode stay out of scope.
