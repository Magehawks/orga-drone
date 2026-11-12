# Discovery: Drone-friendly transition pack (#301)

Status: **Discovery** — no behavior change. Implementation needs separate
PO approval per the issue's own gate.

## Audit of the current transition stack (verified on develop 2f78fb7)

- Canonical types (`studio_transition.py`): **cut**, **crossfade**, **fade
  through black**. Legacy stored values (`""`, `none`, `fade`, `slide`)
  normalize to cut; unknown values fall back to cut — no regression risk
  when reading old projects.
- Region semantics: one transition per Story boundary, duration clamped to
  0.1–2.0 s, occupancy tracked (`occupancy_s`), no overlapping regions.
- Export: the crossfade path uses **ffmpeg `xfade`** chains with a shared
  CFR timebase (`export/studio_encoder.py`); fade-through-black uses the
  `fade` filter chain. Preview approximates the same boundary semantics.
- The `xfade` filter natively supports many more transition styles than
  the three shipped ones — the encoder chain stays, only the transition
  id and its parameter validation would be extended.

## Candidate evaluation (drone-footage fit)

| Candidate | Mechanism | Feasibility | Recommendation |
|---|---|---|---|
| **Blur dissolve** | ffmpeg `xfade` … `hblur`-style transition (available in the pinned ffmpeg v9 line) | **High** — same chain, one new id | Shortlist batch 1 |
| **Luma wipe** | `xfade=transition=wipeleft/right/up/down` (or `distance`-based wipe) | **High** — built-in xfade styles | Shortlist batch 1 |
| **Zoom/spin (drone reveal)** | `xfade=transition=zoomin/circleopen` | **Medium-high** — built-in; needs an intensity/direction clamp review | Shortlist batch 2 |
| **Whip pan / motion blur** | crop-slide + directional blur composition, not a single xfade | **Medium-low** — composite filter graph, parity and performance work | Defer; prototype only after batch 1 ships |
| **Motion match / object-occlusion wipe** | requires motion analysis between clips | **Low** — research-class (#298 dependency) | Out of scope for 2.4.0 |

## Proposed scope for the implementation issue (batch 1)

- Extend `normalize_type`/canonical types with `blur_dissolve` and
  `luma_wipe` (versioned; legacy values keep mapping to cut).
- Validate each new transition's duration/easing against the existing
  0.1–2.0 s clamp; no new parameters beyond direction (left/right) for the
  wipe — avoids parameter explosion per the issue's goal.
- Preview: the still/proxy path approximates the boundary; the export uses
  the same `xfade` chain (parity gate like #320's M-class evidence).
- Regression plan: mixed-FPS/resolution boundaries, differently graded
  clips, speed-ramp and loop-to-soundtrack neighbors (existing conflict
  rules apply), trimmed clips at the boundary.

## Interaction check (verified against current rules)

- Trim/repeat/forward-loop: transitions attach to boundaries; a forward
  loop's own crossfade overlap keeps priority (existing conflict behavior
  unchanged).
- Audio: crossfades overlap audio the same way as today; wipe/dissolve
  variants are video-only boundaries (audio keeps the cut/overlap
  semantics) — to be confirmed in the implementation issue's tests.

## Recommendation

Ship **batch 1 (blur dissolve + luma wipe)** as the first drone-friendly
pack: both are single-`xfade` ids on the existing encoder chain, the
timeline UX stays as-is, and the regression surface is small. Batch 2
(zoom/spin) follows after parity evidence; whip pan and motion match
defer to #298-class work.

PO decision requested: approve batch 1 scope for a follow-up
implementation issue.
