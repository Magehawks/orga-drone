# Issue #325 — Timelapse feasibility (8× / 20×)

Status: **GO** for implementation using the existing ADR 0034 ramp adapter.
Validated maximum speed: **20×**. Probe JSON: `325-timelapse-feasibility.json`.

## Gate result

Constructed flat two-point `SpeedRamp` objects at 8× and 20× (bypassing the
previous 4× parser ceiling only inside the probe) and exported through
`render_ramped_clip` / the shared 30 fps project frame grid.

| Probe | Result |
|-------|--------|
| Python closed-form parity for 120→15 (8×) and 300→15 (20×) | PASS |
| Trimmed flat 8× / 20× exports | PASS (exact frame counts) |
| Mixed Story containing an 8× clip | PASS (75/75 frames) |
| 1080p decoded export at 20× | PASS (~6 s encode for 20 s→1 s synthetic) |
| 4K decoded export at 8× and 20× | PASS (~12–13 s encode for 10 s synthetic) |
| Source bytes unchanged after export | PASS |

No new renderer was required. Legacy `playback_speed` remains 1 / 0.5 / 0.25.

## Contract choice

Raise the shared ramp `MAX_SPEED` from 4 to **20** so Timelapse flat ramps and
manual curves share one validator. Downgrade note: older ≤4× builds treat faster
stored ramps as malformed and fall back to legacy timing. Preview clamps HTML
`playbackRate` at 16×; export keeps the full mapped speed.

## Follow-up product scope

Inspector Timelapse with synchronized target duration and speed multiplier,
explicit Apply, conflict blocking for active ramps / repeats / soundtrack loops,
DE/EN copy, Undo via the existing speed-ramp history path.

## Preview above 16× (review follow-up)

Continuous HTML `playbackRate` is capped at 16. When any ramp point exceeds that
ceiling (including flat 20× Timelapse), Studio pauses decode playback and advances
Story time with wall-clock seek sampling on both preview layers so soundtrack
alignment follows Story time. Export remains the authority for continuous 20×
frame timing. Packaged WebView2 measurement of seek-sampling smoothness on real
drone footage remains a human acceptance item; synthetic export probes do not
claim live preview visual quality.
