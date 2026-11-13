# Studio UX audit and speed-ramp interaction (#295)

Updated: 2026-11-13. Baseline `origin/develop` at `88c79e9`.

This is discovery and design only. It does not change Studio code.

## Evidence basis

- Product and writing: `docs/PRODUCT_VISION.md`, `docs/UX_WRITING.md`
- Timing: ADR 0034 (speed ramp), ADR 0037 (source/story clocks)
- Shipped work: bounded ramp region (#332 / #394), timelapse target duration
  (#325), transitions (#401)
- UI sources: `templates/studio.html` (`#inspector-speed`),
  `static/js/studio/speed-ramp-editor.js`, related Studio inspector strings
- Packaged WebView2 / EXE journey for this audit: **NOT_RUN**

## User task

A hobby or FPV creator selects a clip, chooses constant slow motion, timelapse,
or a variable ramp, adjusts the region or curve, previews, undoes, and exports
without learning a professional NLE.

## Observation

Speed ramp is already shipped as a hybrid: effect-lane bar and curve plus
Inspector controls, including one bounded region. The remaining 2.4.0 problem is
not a missing engine. It is three speed tools in the same Clip → Speed panel
(Timelapse, Speed ramp, Slow motion) with overlapping time fields.

## Recommendation: Concept C (refine the hybrid)

Keep the shipped effect-lane region, compact curve, presets, and point editors.
Do not add a second speed model. For 2.4.0, declutter the Speed panel so one
active speed mode is obvious, keep the region as the primary spatial control,
and treat point editing as secondary.

Rejected:

- Concept A — timeline-only curve: weakens Inspector, presets, and region numbers
- Concept B — Inspector-only keyframes: regresses the shipped bar and handles

## Top usability problems

| Severity | Problem | Evidence |
|---|---|---|
| High | Timelapse, speed ramp, and slow motion stack without a clear mode hierarchy | `#inspector-speed` |
| High | Three similar time fields (region, point time, slow from–to) | Same “(s)” labels |
| Medium | After Apply, the region spans the whole clip; 1× outside is easy to miss | Apply sets a full-span region |
| Medium | Source audio is muted for the whole ramp clip, including 1× flanks | ADR 0034 / user docs |
| Medium | Clip badge emphasises playback speed, not an active ramp | Duration template |
| Low | Long hint blocks; shortcuts appear only when the ramp bar is focused | Current hints vs UX writing |
| Info | Packaged WebView2 journey for this audit | NOT_RUN |

## DE / EN / keyboard (as shipped)

- DE: Geschwindigkeitsrampe, Rampe anwenden, Bereichsanfang/-ende, Zeitraffer, Verlangsamen
- EN: Speed ramp, Apply ramp, Region start/end, Timelapse, Slow motion
- Keys on a focused ramp bar: arrows move; Shift+arrows move the end; Alt+arrows
  move the start; Enter/Space on curve handles focus the speed field; context
  menu removes the ramp

## Explicit non-scope

- Second speed engine or optical flow
- Full Bézier / NLE curve editor
- Multi-region ramps
- Studio redesign
- Production code in this discovery PR

## 2.4.0 viability

Viable and largely shipped. Treat #295 as acceptance and polish of the hybrid
UX, not a rebuild. Any declutter implementation needs a separate PM-selected
follow-up after this recommendation.

## Open product questions

- May the Slow UI collapse while `speed_ramp` is active, without a schema change?
- Is whole-clip audio mute on 1× flanks intended, or a follow-up?
- Who owns packaged E2E for ramp region plus timelapse confirm?

## NOT_RUN

- Packaged WebView2 / EXE with an isolated `ORGA_DRONE_DATA_DIR`
- Live screenshot and flow capture in the running app
- Real-footage quality probe
