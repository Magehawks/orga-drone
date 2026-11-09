# ADR 0034: Source-anchored Studio speed ramps

Status: Accepted; implemented on the speed-ramp branch targeting develop.

## Context

The Product Owner requests variable speed within one clip, four presets, compact
timeline editing, persistence and history, including animated color, repeat and
soundtrack-loop combinations. Existing discovery is #295; this is not a new
rendering architecture. Product and engineering advisors approved this design.

## Decision

An optional `effect_settings.speed_ramp` object stores `v: 1`,
`interp: "reciprocal_smoothstep"`, and 2–5 points with absolute file `source_s`
and `speed` (0.25–4). Points are ordered, finite, and separated by at least
0.05 source seconds. Endpoint speeds extend outside the point range.

Between points, interpolate reciprocal speed using smoothstep. With normalized
source position u and q=1/speed, the integral is
`L * (q0*u + (q1-q0)*(u^3 - 0.5*u^4))`. This gives a strictly monotone map and
smooth speed at joins. Python, JavaScript and FFmpeg use this same definition.
Bounded bisection supplies the inverse. Trimming and splitting retain the
original points; neither operation refits the curve.

Source masks, framing, color, HUD and map retain source clocks. Story overlays
and fades retain output clocks. Grade/LUT builders are unchanged. Non-ramped
clips retain the existing renderer. Ramped loops expand into passes before
color subdivisions; partial tails use inverse mapping.

All derived pieces share output frame boundaries `round(30*T(source))`.
Retiming preserves global sampling phase until final CFR. Endpoint sample
holds cover the mapped boundary, and each piece emits its assigned frame count.
Independent per-piece rounding is forbidden: the discovery probe lost nine
frames across eight pieces. Existing segment encoding/stitching remains in use.

Both preview elements update instantaneous playback rate on the paint loop and
use the same source/Story mapping. Video decode remains the clock authority.
Source audio is muted for the entire ramped clip; soundtrack stays on Story
time. Removing a ramp restores the stored source-audio placement. Applying a
ramp explicitly replaces legacy slow motion; removing it returns to 1×.

The selected UX is a compact curve in the existing Effect lane, with presets
and selected-point numeric controls in the Speed inspector. Each completed
gesture uses existing history grouping.

## Compatibility and rollback

No SQLite schema migration. A missing key preserves existing behavior; malformed
stored values fall back to the legacy path, while writes reject malformed data.
Existing project snapshots already retain the complete JSON. Unrelated keys
must survive every save. Old versions ignore this key and cannot reproduce
ramped timing; remove ramps in a supporting version before downgrading.

## Performance and limits

A story with no ramp keeps the existing encoder path and continuous durations.
A ramped clip is a timing adapter: source samples stay intact until one
nonlinear `setpts` and the final 30 fps step. Slow sections repeat source
frames and fast sections omit them. There is no optical flow. Source audio is
silent for the whole ramped clip, including stretches that pass through 1×.
Preview updates `playbackRate` on the existing paint loop. The browser may drop
preview frames on demanding 4K playback; that does not change the export.
The compact curve in [assets/0034-speed-ramp-curve.png](assets/0034-speed-ramp-curve.png)
is the selected interaction. Source-app WebView2 measurements use synthetic
60 fps media. They do not establish private drone footage quality or packaged
release readiness.

## Validation requirement

Shared mapping fixtures, trim/cut, transitions, history, reopen, malformed values,
real MP4 decoding and source immutability are required. Frame identity at joins
must stay within one output frame without accumulated drift. Preview measurements
must distinguish startup latency and in-flight error. Actual Windows/WebView2
coverage must exercise both video layers and 1080p/4K sources; synthetic evidence
does not establish real-footage visual quality or packaged release readiness.
