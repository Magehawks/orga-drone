# Drone-friendly transition pack: discovery (#301)

Status: **discovery complete; GO for a bounded follow-up, no implementation in
this change.** This document audits the current Studio transition system,
evaluates the requested transition ideas, records reproducible FFmpeg probes,
and recommends a two-effect V1 scope. It does not ship new transitions and does
not change product status.

Snapshot: `develop` at `660f3dd` (2026-11-05), Windows host, Python 3.12,
bundled FFmpeg 7.1 (`imageio-ffmpeg`). Measurements are synthetic and
CPU-only; see [Limitations](#11-limitations).

Related: issue #301, issue #211 (animated color), issue #182 (timeline
transition UX), issue #295 (speed-ramp UX discovery), issue #298 (motion
tracking), ADR 0010 (visual transitions), ADR 0028 (LUT preview stills).

## 1. What exists today

Only three story transitions are **Available now**. Anything else remains
**Later** until a separately approved implementation issue ships it.

| Area | Current behavior |
|---|---|
| Persistence | `studio_clips.transition` stores `cut`, `fade_black`, or `crossfade`; `transition_duration_s` stores the remembered duration. Unknown or legacy values normalize to `cut`. The outgoing clip owns the boundary. |
| Timing | Duration is clamped to 0.1-2.0 s in 0.1 s steps. Crossfade overlaps and shortens the story; fade-through-black is sequential (D/2 out + D/2 in). Every neighbor keeps at least 0.1 s outside the effect, otherwise the boundary falls back to a cut. |
| Timeline | A chip sits between adjacent clips. Selecting it opens the transition inspector with type and duration. There is no draggable transition region and no extra transition track. |
| Preview | `studio_transition.resolve_story_time()` returns the primary clip, the optional crossfade partner, overlap progress, and fade-black opacity. `studio.js` stacks the two video/photo layers and animates CSS opacity. It is an approximation, not a pixel match (ADR 0010). |
| Export | Each clip is rendered to a segment. Crossfade uses `xfade=transition=fade`; fade-through-black uses `fade=` before concat. `xfade` and concat pads are normalized to shared FPS/timebase. |
| Audio | Hard cut at the clip edge, or at the midpoint of a crossfade overlap. Story transitions never crossfade audio. |
| Loops | Repeated sections have their own `loop_transition` choices: `crossfade`, `cinematic` (smoothstep `xfade` custom expression), and experimental `match` (local seam search). These are not exposed as story transitions and must not be duplicated blindly. |
| Tests | `studio_transition` unit tests plus encoder regression tests for cut, fade black, one crossfade, chained crossfade with/without music, and title-card crossfade. |

The shared timing helpers already provide the correct contract for any new
transition type: `occupancy_s`, `apply_boundaries`, `story_length_s`,
`story_starts_s`, and `resolve_story_time`. New types should reuse them rather
than introduce a second timeline model.

## 2. Inherited constraints

1. Persist canonical type ids, never FFmpeg filter text (ADR 0010).
2. Reuse the outgoing-boundary model, duration clamp, fallback-to-cut behavior,
   and one-sided/two-sided occupancy budget.
3. Crossfade-like transitions are overlaps; fade-through-black-like transitions
   are sequential. Do not silently change story length semantics.
4. Preview and export must describe the same effect. Do not ship an
   export-only transition.
5. Audio stays a hard cut unless a separate issue approves audio crossfades.
6. Existing projects and the three current types must keep their behavior.
7. Trim, speed pieces, color animation pieces, and loop joins are rendered
   before the story stitch. Story transitions apply to finished segment files,
   so new types should compose with those features without rewriting them.

## 3. Candidate evaluation

Scoring is for drone footage and the current Studio architecture, not for a
general NLE.

| Candidate | Value for drone clips | Export feasibility | Preview feasibility | Verdict |
|---|---|---|---|---|
| **Blur dissolve** | High. Softens scenery cuts and hides small exposure or horizon jumps without a visible slide direction. | Native `xfade=transition=hblur`; measured cost is essentially the same as the existing fade. | CSS `filter: blur()` + opacity on stacked layers is a credible approximation, but needs a parity check against `hblur`. | **GO for V1** |
| **Soft directional wipe** (left/right/up/down) | High. Reads as a deliberate reveal and suits lateral drone moves. Native `smoothleft`/`smoothright`/`smoothup`/`smoothdown` are cheap. | Native `xfade` transitions; same cost class as fade. | CSS animated `mask-image`/clip-path can approximate the direction and edge softness. Needs WebView2 validation. | **GO for V1** |
| **True luma wipe** (threshold follows image luminance) | Medium. Visually similar to a soft directional wipe for most aerial footage. | Possible with `xfade=transition=custom` and an X/Y threshold expression. Measured **~5.7x** the fade cost at 1080p and **~5.8x** at 4K. | Harder: CSS has no per-pixel luminance threshold. Would need stills/proxy or a shader. | **NO-GO for V1**; keep as a later parity spike |
| **Whip pan / motion blur** | Medium. Can feel energetic, but direction must match the shot movement; arbitrary direction looks artificial. | Possible by pre-blurring both inputs and using a slide `xfade` (probe below), but it is a composition of effects rather than a native transition. | CSS transform + blur can approximate, but direction, overshoot, and blur strength need parameters and careful parity. | **NO-GO for V1**; revisit with UX evidence |
| **Zoom / spin** | Low-to-medium. Built-in `zoomin` exists, but it is a gimmick risk and adds parameter surface. | Native `zoomin` is cheap. | CSS scale/rotate approximation possible. | **NO-GO for V1** |
| **Motion match / object occlusion wipe** | Potentially high, but requires motion tracking and semantic understanding. | Not practical with current story transitions; depends on #298 and possibly #299. | Depends on tracked masks/preview. | **NO-GO**; blocked by #298 |

The strongest value-to-risk pair is **blur dissolve + soft directional wipe**.
Both are native, cheap, directionally distinct from a crossfade, and fit the
existing overlap model.

## 4. FFmpeg probe

### 4.1 Available transitions

The bundled FFmpeg 7.1 build reports 59 `xfade` transition values from `-1`
(`custom`) to `57`, including `fade`, `dissolve`, `wipeleft/right/up/down`,
`smoothleft/right/up/down`, `hblur`, `radial`, `pixelize`, `zoomin`, and
`custom`. Availability is a property of the bundled binary, so the implementation
must verify the chosen ids against the pinned FFmpeg version at build or test
time instead of assuming every future build has them.

### 4.2 Probe method

Synthetic 1920x1080 and 3840x2160 `testsrc2` clips were encoded with
`libx264 -preset ultrafast`. Two clips were joined with a 0.5 s (1080p) or
0.3 s (4K) overlap using this pattern:

```text
ffmpeg -y -i a.mp4 -i b.mp4 \
  -filter_complex "[0:v][1:v]xfade=transition=<id>:duration=D:offset=O[v]" \
  -map "[v]" -an -c:v libx264 -preset ultrafast -crf 20 -pix_fmt yuv420p out.mp4
```

Custom luma wipe used this expression (commas escaped inside the filter graph):

```text
xfade=transition=custom:expr=
A*(1-min(max((X/W-(P*1.2-0.1))/0.1\,0)\,1))+
B*min(max((X/W-(P*1.2-0.1))/0.1\,0)\,1)
```

The tested whip-pan approximation pre-blurred both inputs and used a slide:

```text
[0:v]boxblur=20:2[l];[1:v]boxblur=20:2[r];
[l][r]xfade=transition=slideleft:duration=0.5:offset=1.5[v]
```

### 4.3 Measured results

1080p, 2 s outputs (one 0.5 s overlap), relative CPU time:

| Transition | Wall time | Output size |
|---|---:|---:|
| `fade` (existing crossfade) | 482 ms | 7.85 MB |
| `hblur` (blur dissolve) | 483 ms | 6.62 MB |
| `wipeleft` | 477 ms | 6.97 MB |
| `smoothleft` (soft wipe) | 500 ms | 7.43 MB |
| `radial` | 621 ms | 7.16 MB |
| `dissolve` | 671 ms | 15.13 MB |
| custom fade expression | 1032 ms | 8.01 MB |
| custom luma wipe | 2756 ms | 7.15 MB |
| blur + slide whip approximation | 1418 ms | 1.11 MB |
| blur + `tmix` whip approximation | 1650 ms | 0.94 MB |

4K, 1 s outputs (one 0.3 s overlap):

| Transition | Wall time |
|---|---:|
| `fade` | 1199 ms |
| `hblur` | 1172 ms |
| `wipeleft` | 1123 ms |
| custom luma wipe | 6919 ms |

Observations:

- Native `hblur` and `smoothleft` cost the same order as `fade`.
- A true per-pixel luma expression costs about 5.7-5.8x a native transition.
  That may still be acceptable for short overlaps, but it is not free at 4K and
  it has the weakest preview story.
- The whip-pan probe visually reads as a blur/slide, not as a matched camera
  move. It also compressed to a much smaller file because the blurred frames
  contain less detail. It needs a dedicated UX concept before it deserves a
  user-facing name.
- `xfade` applies after per-segment rendering, so grading, LUTs, color
  animation, and speed pieces are already baked into each side of the join.

### 4.4 Preview consequences

The current preview only has opacity and a black overlay. A blur dissolve can
reuse the stacked layers with a CSS blur; a soft wipe needs an animated
`mask-image` or clip path. Neither is guaranteed to match the FFmpeg filter
pixel-for-pixel. Before implementation, a WebView2 parity spike must compare
paused and moving frames for:

- transition start, middle, and end;
- both directions;
- differently graded/LUT-resolved neighbors;
- 1080p and 4K sources;
- packaged EXE, not only source-mode browser.

If CSS cannot stay within an agreed tolerance, the fallback is a
transition-aware still/proxy path, not a fake CSS approximation that is sold as
the rendered result.

## 5. Recommended V1 contract (proposal, not implemented)

### 5.1 Types and storage

Recommended canonical ids, stored in the existing `transition` column:

- `blur_dissolve` - overlap, same occupancy as `crossfade`.
- `soft_wipe_left`, `soft_wipe_right`, `soft_wipe_up`, `soft_wipe_down` -
  overlap, same occupancy as `crossfade`.

Direction is encoded in the canonical id so no SQLite migration or new column
is required. If the product later needs more directions or intensity, that is a
separate schema decision.

Rejected for V1: `whip_pan`, `luma_wipe`, `zoom`, `spin`, `motion_match`.

### 5.2 Rendering map

| Stored type | Export | Preview |
|---|---|---|
| `blur_dissolve` | `xfade=transition=hblur` | stacked layers + CSS blur + opacity |
| `soft_wipe_left` | `xfade=transition=smoothleft` | animated mask/clip reveal from the right edge |
| `soft_wipe_right` | `xfade=transition=smoothright` | mirrored |
| `soft_wipe_up` | `xfade=transition=smoothup` | bottom-to-top reveal |
| `soft_wipe_down` | `xfade=transition=smoothdown` | top-to-bottom reveal |

No intensity value in V1. Duration is the only user control, matching the
current transition inspector. This avoids parameter explosion and keeps preview
and export mapping small.

### 5.3 UI

- Extend the existing transition type select; do not add a new track.
- Group the new labels under a short "Drone pack" heading or equivalent.
- Show direction only as four concrete labels, not a free-form angle.
- Keep the existing duration field and fallback/clamp hints.
- Chip labels: "Blur" and "Wipe" with an accessible full name.
- German and English strings are required.

### 5.4 Interactions to preserve

- **Trim:** the outgoing clip owns the transition; trimming reduces the
  available duration and falls back to cut when the budget is violated.
- **Speed ramp:** slow pieces are rendered and concatenated before the story
  stitch; the transition still applies at the original clip boundary.
- **Color animation / LUT:** each segment is graded before `xfade`; the
  transition blends graded frames and must not bypass the color path.
- **Forward loop:** loop joins keep `loop_transition`; do not copy the story
  transition onto internal repeat joins.
- **Music:** story length changes exactly like a crossfade; soundtrack mixing is
  unchanged.
- **Undo/redo:** reuses the existing transition save/history path.
- **Reload:** unknown ids normalize to cut; old projects stay unchanged.

## 6. Test plan for the follow-up implementation

Automated:

- Transition normalization: new ids round-trip; unknown ids become cut.
- Occupancy/story length: same as crossfade for every new id; clamp and
  fallback behavior at short neighbor durations.
- Encoder: synthetic two-clip render for each new type; duration and audio
  presence; no frame gaps at the join.
- Preview mapping: Node test that the resolved progress/direction reaches the
  preview layer.
- Preview/export parity: representative start/mid/end frames with documented
  tolerances, including graded and LUT-resolved neighbors.
- Regression: existing cut, fade-through-black, crossfade, chained crossfade,
  loop-transition, speed, color-animation, and project-reload tests still pass.
- Source media SHA-256 unchanged.

Manual (Windows packaged EXE/WebView2):

- Select each transition, scrub the overlap, play through it, export, and
  compare.
- Change duration and observe clamp/fallback hints.
- Trim a neighbor until fallback to cut.
- Reload the project and undo/redo the transition edit.

## 7. Acceptance criteria for a follow-up issue

- Two new transition types are discoverable in the existing inspector and show
  a correct chip on the timeline.
- Duration and story-length behavior match a crossfade; no frame gaps or audio
  desync.
- Preview and export match within documented tolerances for start, middle, and
  end; if preview parity is not achievable, the feature is not shipped.
- Existing three transition types, project files, loops, speed, and color
  animation remain compatible.
- DE/EN strings, docs, and ADR 0010 (or a new ADR) are updated.
- Packaged Windows GUI evidence exists.

## 8. Recommendation

**GO for a bounded implementation issue:** blur dissolve plus four soft-wipe
directions, native FFmpeg transitions, duration-only controls, no new track,
and a mandatory preview/export parity spike before the UI is called complete.

**NO-GO for V1:** true luma wipe, whip pan, zoom/spin, motion match, and
object-occlusion wipes. Luma wipe is technically possible but costs ~5.7x and
has the weakest preview path. Whip pan and motion match need a UX concept and,
for tracking-based variants, #298 first.

**No code is added by this discovery PR.**

## 9. Limitations

- Probes used synthetic `testsrc2`, not real drone footage. Haze, foliage,
  water, and moving subjects can change perceived quality and encode cost.
- Measurements are CPU-only, `libx264 -preset ultrafast`, and not a promise for
  the packaged EXE, hardware encoders, or 4K export latency.
- No real Windows WebView2 GUI session was run for this document; CSS preview
  feasibility is an engineering assessment, not measured evidence.
- `xfade` transition availability depends on the bundled FFmpeg build. Verify
  the ids in the pinned version before implementation.
- Custom expressions are harder to keep portable across FFmpeg builds than
  native transition ids; this is another reason to prefer native types in V1.
- This document does not approve UX, architecture, or release scope. Those
  gates remain with the human/PM/CTO workflow in `docs/AGENT_WORKFLOW.md`.
