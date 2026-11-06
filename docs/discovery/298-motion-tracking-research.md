# Reusable local motion tracking for masks and overlays: research (#298)

Status: **research complete; conditional GO for a bounded manual-target tracking
foundation spike, NO-GO for Subject Focus or portrait auto-reframe until the
tracked-mask PoC and packaging decision pass.** This document does not add
tracking to Studio and does not change product status.

Snapshot: `develop` at `660f3dd` (2026-11-05), Windows host, Python 3.12,
bundled FFmpeg 7.1. The PoC used a synthetic clip and an environment-local
OpenCV build; see [Limitations](#9-limitations).

Related: issue #298, issue #299 (Subject Focus), issue #300 (portrait
auto-reframe), issue #81 (privacy masks), issue #86 (zoom/pan), issue #178
(lens/Gyroflow research), issue #189 (preview/export parity), ADR 0017
(privacy masks), ADR 0018 (framing), ADR 0032 (Control API).

## 1. What exists today

Studio has no tracking. The product docs explicitly say masks, zoom/pan, HUD,
and map are not tracking.

| Area | Current contract | Tracking gap |
|---|---|---|
| Privacy masks | Up to 8 rectangular masks per clip, normalized to the fitted picture, effect `blur` or `pixelate`, optional start/end time. No per-frame transform. | A mask cannot follow a moving subject. |
| Overlays | Rectangular text/shape/image overlays with normalized coordinates plus entrance/exit animation. No per-frame transform. | An overlay cannot stay on a moving subject. |
| Zoom/pan | Start/end zoom plus a start/end focal point. Two-point motion, not an arbitrary track. | Not a tracking foundation. |
| Time basis | Clip-local source seconds for masks, overlays, color animation, and saturation ramps. Export segments seek with `-ss`, so filter time starts at the clipped in-point. | A track must use the same source-time basis. |
| Persistence | Effect data lives in `studio_clips.effect_settings` JSON. A SQLite schema change or a new `effect_settings` shape needs an ADR and migration/validation plan. | Track samples may not fit cheaply in the existing JSON. |
| Export | Masks are baked with fixed `crop`/`boxblur`/`overlay` filters. Overlays use `overlay` with optional expressions. | A moving mask needs time-varying crop/overlay coordinates or pre-split segments. |
| Preview | Canvas/DOM overlays and CSS/CSS-filter layers. Paused LUT stills are per-clip, not composed with moving masks/overlays. | Faithful moving-mask preview is an open parity problem. |

`track_json` in the media table is DJI telemetry (GPS/altitude), not picture
tracking. It must not be reused for target tracks.

## 2. Required foundation for #299 and #300

Subject Focus (#299) and portrait auto-reframe (#300) both need the same
primitive: a user-selected target that yields a reliable transform over time,
with manual correction. A shared contract should provide:

- manual target selection (bounding box) without semantic recognition;
- per-frame or per-keyframe transform samples in source time;
- explicit confidence/lost state, never silent drift;
- user correction, stop, and re-track from a point;
- one track shared by a mask, overlay, frame, or reframe consumer;
- deterministic preview/export evaluation;
- stable behavior under trim, split, speed, repeat, loop, transitions, and
  project reload;
- no source-media modification.

## 3. Approaches evaluated

### 3.1 OpenCV model-free trackers

OpenCV offers MIL out of the box in the installed wheel. CSRT and KCF are
usually in the `contrib`/legacy modules and were not available in this build.
Newer trackers (`DaSiamRPN`, `Nano`, `Vit`, `GOTURN`) require model files that
are not in this repository; downloading them at runtime would conflict with the
local-first, no-required-network position and would need license review.

The PoC used MIL and a sparse Lucas-Kanade (LK) optical-flow tracker. MIL ran at
about 20 fps on a 720p synthetic clip but silently drifted after an occlusion.

### 3.2 Sparse Lucas-Kanade optical flow plus reacquisition

Sparse LK on features inside the target box is fast and model-free. In the PoC
it was pixel-accurate before the occlusion. It failed after the target was
hidden because the target moved outside the local search region and the point
set was lost.

Adding three safeguards made it work on the synthetic clip:

1. forward-backward flow error filtering;
2. an explicit "lost" state when too few points survive;
3. a template-matching reacquisition search when lost, followed by re-seeding
   features inside the recovered box.

This is not production-grade, but it proves the useful primitive: tracking plus
an explicit lost/reacquire state is feasible without a neural model.

### 3.3 FFmpeg-only options

The bundled FFmpeg has `vidstab` and `deshake`. They estimate global camera
motion for stabilization; they do not follow a user-selected object. `mestimate`
exposes codec motion estimation, not a target tracker. Using global stabilization
as a substitute would not satisfy #299 or #300 and would risk double-cropping
already-stabilized drone footage (see #178).

### 3.4 Learned trackers

Object detection, segmentation, or learned tracking models are out of scope for
this foundation. They add model files, runtime, licensing, and failure modes
that are not justified for a manual-target workflow. The issue explicitly says
no AI object recognition is required.

## 4. PoC

### 4.1 Setup

Synthetic 1280x720 clip, 96 frames at 30 fps:

- textured background with a slow camera pan;
- a distinctive high-contrast target with independent motion;
- a 12-frame occlusion where a neutral bar hides the target;
- ground-truth box per visible frame.

This deliberately avoids private media. The target is not a real person, boat,
or vehicle; real footage will be harder.

### 4.2 Results

| Approach | Speed (720p) | Before occlusion | After occlusion | Lost signal |
|---|---:|---|---|---|
| OpenCV MIL | 20 fps | drifted (mean error 120 px overall) | did not recover | none |
| Sparse LK | 250 fps | 0 px mean/max error | 209 px mean, 337 px max | 13 lost updates |
| Sparse LK + template reacquisition | 99 fps | 0 px mean/max error | 0 px mean/max error after 1 reacquisition | explicit |

Downscaled 4K experiment: tracking LK on 4K frames resized to 720p ran at about
511 fps excluding the resize cost. Tracking at reduced resolution is practical,
but the PoC did not exercise scale, rotation, perspective, motion blur, or real
occlusion.

Interpretation:

- LK is fast and accurate while the target is visible and well textured.
- Without explicit loss detection, both tested approaches are unsafe: MIL drifted
  silently; LK froze on stale points.
- A fixed-template reacquisition recovered the synthetic target, but a real
  tracker must also handle scale and rotation. CSRT/KCF or a similar robust
  model-free tracker would be a better production candidate, which means
  `opencv-contrib-python` or a vendored equivalent, not the installed build.
- The PoC does not yet prove export parity for a moving mask, which is the
  harder half of the feature.

### 4.3 Packaging and license cost

The environment-local OpenCV install is not a project dependency:

| Item | Observed |
|---|---|
| `cv2` directory on this host | about 106 MB |
| `cv2.pyd` | about 71 MB |
| `numpy` directory on this host | about 29 MB |
| License | Apache 2.0 |
| In `requirements.txt` / `pyproject.toml` | No |
| PyInstaller integration | Not present; would need binaries/hidden imports and notices |

OpenCV is license-compatible with MIT, but adding roughly 100 MB or more to the
Windows onefolder, plus third-party notices and packaging tests, is a product
decision. A headless wheel may be smaller, but the packaging spike must measure
the actual zip and startup cost. A pure FFmpeg + NumPy/Pillow tracker would avoid
the dependency but needs a separate performance and quality proof.

## 5. Proposed shared contract (not implemented)

### 5.1 Data model

A versioned track record, stored once per clip and referenced by consumers:

```text
Track
  v: int
  source: "manual" | "tracked"
  target: initial normalized box {x, y, w, h}
  samples: [{t, x, y, w, h, confidence, lost}]
  interpolation: "hold" | "linear"
  max_samples / sample_step
```

- Coordinates are normalized to the source picture, matching masks and
  overlays after the existing fit/zoom rules.
- `t` is clip-local source seconds, matching masks, overlays, and color
  animation.
- `lost` ranges are explicit. A lost sample must not silently reuse the last
  transform as if it were valid.
- The resolver exposes `transform_at(track, source_time_s)` and one canonical
  interpolation rule shared by preview and export.
- `confidence` is optional metadata for the UI; it is not a truth claim.

### 5.2 Storage

High-frequency samples can become large (for example 30 s at 30 fps is 900
samples). Do not put an unbounded sample array into `effect_settings` without
measuring the JSON size and view-model cost. Options:

1. a dedicated `studio_tracks` table keyed by clip id with a versioned JSON/blob;
2. a sidecar file under the app data directory, referenced by a stable key;
3. a compact keyframe-only representation with a bounded sample count.

This needs an ADR and migration plan before implementation. A track should be
invalidated or revalidated when the source identity, trim, or path changes; the
existing `loop_match` key pattern is a useful precedent.

### 5.3 Consumers

- A mask or overlay references a `track_id`; it does not duplicate tracking.
- The frame/reframe consumer reads the same track center and applies its own
  smoothing and output aspect rules.
- A manual correction writes a track keyframe and marks subsequent automatic
  samples as needing re-tracking or as user-locked.
- "Stop tracking" leaves the last valid transform and does not delete samples.

### 5.4 Timing interactions

- **Trim/split:** crop or shift samples with the existing clip-relative time
  helpers. A split must not shift the right side's track incorrectly.
- **Speed:** samples are source-time based, so a slowed piece maps source time.
  Do not store story time.
- **Repeat/loop:** the same source track applies to each play; joins keep their
  existing transition behavior.
- **Transitions:** each clip segment is rendered before the stitch; the track
  applies inside the segment.
- **Undo/redo and reload:** track edits need the same history guard and
  validation as other effect settings.
- **Source loss:** missing media stays an offline clip; tracking data remains
  stored but cannot be previewed or exported.

## 6. Export and preview parity risks

A moving rectangular blur mask is harder than a static one:

- the current export graph crops a fixed window and overlays it at fixed
  coordinates;
- moving coordinates require time-varying `crop`/`overlay` expressions or
  splitting the clip into many short constant-transform pieces;
- long expressions and many segments increase encode time and failure surface;
- the paused LUT still path renders one clip frame, not a composed moving-mask
  frame; it would need a mask-aware still or an explicit approximation notice;
- continuous playback would need a canvas/DOM transform that matches the export
  transform within a documented tolerance.

The first implementation must therefore be a **tracked rectangular blur mask
PoC** with measured preview/export parity. Subject Focus and portrait reframe
must not start until that PoC is accepted.

## 7. Recommendation

### GO (conditional)

- A bounded foundation spike: manual box selection, sparse LK, explicit
  lost-state detection, local reacquisition, and manual correction for one
  tracked rectangular blur mask.
- A packaging/ADR spike that chooses between OpenCV (with notices and measured
  zip/startup cost) and a pure-FFmpeg/NumPy approach.
- A parity spike for moving mask preview vs MP4 export, including start, middle,
  end, and an occlusion/lost interval.
- Only after this passes: consider #299 Subject Focus. #300 portrait reframe
  follows separately and must prove crop bounds and portrait export parity.

### NO-GO (for now)

- Shipping tracking UI or claiming tracked masks in product docs before the PoC
  and packaging decision.
- Automatic person/boat/car recognition or learned segmentation.
- Reusing `track_json` telemetry as picture tracking.
- Starting #299 or #300 before #298's tracked-mask foundation is ready.
- Depending on downloaded model files or a required network service.

## 8. Acceptance criteria for a follow-up issue

- A 5-10 s local fixture with manual target selection and a tracked rectangular
  blur mask; no private media committed.
- Correct alignment at representative visible frames and explicit lost-target
  behavior during occlusion.
- User can correct, stop, or re-track; no silent drift.
- Preview and MP4 export match within documented tolerances for start, middle,
  end, and a lost interval.
- Trim, split, speed, repeat, loop, transitions, Undo/Redo, and project reload
  preserve the intended track.
- Source media is unchanged.
- Packaging size, startup time, licenses, and third-party notices are documented.
- Real Windows WebView2 GUI evidence and a real drone-clip validation are
  provided; otherwise the feature is not called complete.

## 9. Limitations

- The PoC is synthetic, 720p, with a synthetic target and a fixed template.
  Real drone footage has scale, rotation, perspective, motion blur, water,
  foliage, and partial occlusions that this clip does not model.
- The installed OpenCV build lacks CSRT/KCF; the PoC used MIL and LK only.
- OpenCV and NumPy are environment-local in this probe, not project
  dependencies. The installed sizes are not a packaged-zip measurement.
- No moving-mask export, no preview/export parity test, no WebView2 GUI, and no
  packaged Windows EXE were run for this research.
- The fixed-template reacquisition is a proof of the lost/reacquire principle,
  not production tracking.
- This document does not approve product scope, UX, architecture, or release.
