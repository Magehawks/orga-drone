# #295 Speed Ramp UX discovery → ADR 0034

Status: Closed by design decision ADR 0034; implementation follows that ADR.

## Recommendation (accepted)

**Option C (hybrid, compact):** Effect-lane curve on the selected clip + Speed
inspector presets and numeric point controls. Not a full Bézier keyframe editor
and not inspector-only keyframes.

Creator flow: select video → Clip → Speed ramp → choose preset → Apply ramp →
preview → drag/edit points → Undo/Redo → save/reopen → export.

## Scope for MVP

- Variable speed inside one clip via 2–5 source-anchored points (0.25×–4×).
- Four presets: Slow→Fast→Slow, Fast→Slow→Fast, Smooth Acceleration,
  Smooth Deceleration.
- Reciprocal smoothstep interpolation shared by preview, Python and FFmpeg.
- Source audio muted for ramped clips; soundtrack stays on Story time.
- Preserve constant slow motion (`playback_speed` / `slow_bar`) when no ramp.

## Deferred

Optical flow, beat sync, unrestricted Bézier editor, cloud services, full Studio
redesign, and pitched/time-stretched source audio.

## Engineering note

No new rendering architecture. See `docs/decisions/0034-studio-speed-ramp.md`.
