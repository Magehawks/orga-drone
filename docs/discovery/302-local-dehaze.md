# Local dehaze control for aerial photos and video: discovery (#302)

Status: **discovery complete; GO for a bounded global-strength control after
real-fixture validation, NO-GO for per-pixel dark-channel dehaze in the current
FFmpeg-only path.** This document does not add a slider and does not change
product status.

Snapshot: `develop` at `660f3dd` (2026-11-05), Windows host, Python 3.12,
bundled FFmpeg 7.1 (`imageio-ffmpeg`). The probe used a synthetic scene; see
[Limitations](#9-limitations).

Related: issue #302, issue #76 (image adjustment), issue #296 (MCP image
support), issue #283 (real drone footage fixtures), ADR 0011 (image adjust),
ADR 0027 (LUT color order), ADR 0028 (LUT preview stills).

## 1. What exists today

Studio has no Dehaze control. The current per-clip color tools are:

| Control | Stored as | Current effect |
|---|---|---|
| Exposure / contrast / saturation / warmth | `effect_settings.image` | `exposure`, `eq`, `colortemperature` in the export grade chain |
| Highlights / shadows / blacks | `effect_settings.image` | restrained per-channel `colorlevels` |
| HSL mixer | `effect_settings.hsl` | hue-selective adjustments |
| Color wheels | `effect_settings.color_wheels` | lift/gamma/gain-style corrections |
| Creative / conversion LUT | `effect_settings` via `studio_lut` | `lut3d`, optional technical conversion |
| Detail | `effect_settings.detail` | sharpen / denoise |
| Saturation ramp and color animation | `effect_settings` | time-based color changes |

Export order is **grade -> LUT -> detail -> saturation ramp** (ADR 0027). Paused
and scrubbed previews use FFmpeg stills through the same grade+LUT builders
(ADR 0028); continuous playback stays a CSS approximation without a LUT and
shows an honesty chip.

This matters for Dehaze: it must state where it sits in that chain, and it must
not become another slider that duplicates contrast, highlights, shadows, or
blacks without measurable incremental value.

## 2. What the requested control must improve

Aerial haze is an additive, depth-dependent veil: distant pixels are brighter,
lower-contrast, and shifted toward the atmospheric color, while nearby pixels
are much less affected. Global contrast alone cannot separate the two. A useful
Dehaze control should:

- restore midtone and shadow separation in hazy footage;
- reduce the washed-out atmospheric veil without crushing foreground shadows;
- avoid unacceptable halos, noise amplification, or sky color shifts;
- stay local, deterministic, non-destructive, and preview/export consistent;
- remain understandable as one strength control, not a second color suite.

## 3. Approaches evaluated

### 3.1 Existing manual controls only

Users can already raise contrast and saturation and adjust highlights/shadows/
blacks. This is the baseline to beat. In the probe, a strong manual contrast
attempt over-brightened the scene and reduced similarity to the clean reference
(see results). It is not a substitute for removing the atmospheric veil.

### 3.2 Local-contrast approximation without a physical model

A chain such as `eq=contrast=...:saturation=...` plus `unsharp` and `vibrance`
adds local edge contrast. It is cheap and FFmpeg-native, but it does not
separate depth-dependent haze from real detail. It also raises edge energy and
noise, and it can create halos. In the probe it barely improved PSNR and reduced
SSIM relative to the hazy input.

### 3.3 Global atmospheric-light subtraction

Estimate one atmospheric-light color for the clip (for example from the
brightest pixels of the dark channel), then apply a per-channel linear
transform that removes a controllable fraction of that veil:

```text
t = 1 - strength * (1 - t_min)          # t_min ~ 0.5 at full strength
J = (I - A * (1 - t)) / t
```

FFmpeg can express the per-channel transform with `colorlevels`, optionally
followed by a restrained saturation lift. This is deterministic, cheap, and
works in the existing FFmpeg filter graph. It cannot model depth variation
perfectly, so very strong strengths can darken the foreground or clip
highlights. That is why the recommendation is a bounded strength range and a
neutral default.

### 3.4 Dark-channel prior with local transmission

The classical local approach estimates a per-pixel transmission map, refines it
with a guided filter, and recovers `J = (I - A) / t + A`. It produced the
strongest contrast restoration in the probe, but:

- the bundled FFmpeg build has no `defog`/dehaze filter and no `frei0r`
  integration;
- the current export path is FFmpeg filter graphs plus segment files, not a
  Python frame-processing pipeline;
- a per-frame Python/NumPy/OpenCV pass would require decoding, processing, and
  re-encoding every frame, and would be very slow at 4K;
- the probe still showed sky color shifts, foreground darkening, and amplified
  noise/halos;
- OpenCV is **not** a project dependency in `requirements.txt` or
  `pyproject.toml`; the dev host only has it because of unrelated packages.

A true local implementation would need an approved custom FFmpeg filter, GPU
shader, or a new processing pipeline, plus packaging and preview-parity work.
That is a separate architectural decision, not a slider addition.

### 3.5 Generative or AI dehaze

Out of scope. Orga Drone does not add generative AI, external AI APIs, or cloud
processing.

## 4. Probe method

A synthetic 1280x720 aerial-like scene was created with Pillow: sky gradient,
distant hills, lake, foreground fields, dark forest, rocks, buildings, and a
road. Haze was simulated with the atmospheric-scattering model:

```text
I = J * t + A * (1 - t),   t = exp(-beta * depth)
```

with `beta = 0.85`, depth increasing toward the horizon, atmospheric light
`A = (0.82, 0.86, 0.90)`, and mild sensor noise. The same clean and hazy
images were then processed by:

- existing manual controls (contrast + saturation; contrast + highlights);
- a local-contrast approximation (`eq`, `unsharp`, `vibrance`);
- global atmospheric subtraction at half strength and full strength, once in
  Python and once with FFmpeg `colorlevels`;
- a dark-channel prior with guided filtering in Python/OpenCV.

Metrics are PSNR and SSIM against the synthetic clean image, mean RGB, and a
mean-gradient ratio versus the clean image. PSNR/SSIM are useful for controlled
comparison, not a substitute for human judgment.

## 5. Probe results

| Variant | PSNR | SSIM | Mean RGB | Gradient ratio |
|---|---:|---:|---|---:|
| Hazy input | 12.92 | 0.8115 | 142, 167, 174 | 1.472 |
| Manual contrast + saturation | 11.57 | 0.7393 | 145, 185, 192 | 2.247 |
| Manual contrast + highlights | 9.41 | 0.7089 | 165, 205, 211 | 2.377 |
| Local-contrast approximation | 13.19 | 0.7441 | 136, 171, 175 | 2.860 |
| Global atmospheric, half strength (Python) | 15.96 | 0.8166 | 116, 151, 163 | 2.021 |
| Global atmospheric, full strength (Python) | 20.45 | 0.7738 | 74, 126, 147 | 2.910 |
| Global atmospheric, half strength (FFmpeg) | 16.18 | 0.8049 | 112, 153, 162 | 2.048 |
| Dark-channel prior + guided filter | 19.82 | 0.7425 | 63, 119, 143 | 2.973 |

Interpretation:

- Existing manual contrast and tonal controls do not restore the haze scene;
  they mostly brighten or clip it.
- Moderate global atmospheric subtraction improved both PSNR and SSIM over the
  hazy input with a small gradient increase. Full strength restored more
  contrast numerically but visibly over-darkened the foreground and lost
  shadow detail.
- The local-contrast chain added edge energy without recovering the depth
  relationship.
- The dark-channel prior restored contrast but shifted the sky, darkened the
  scene, and amplified noise/halos. It is the most promising quality path, but
  not with the current architecture.
- The FFmpeg `colorlevels` implementation is close to the Python half-strength
  variant (small differences from rounding and the saturation step).

### 5.1 Cost measurements

4K, 1 s, 30 fps, `libx264 -preset ultrafast -crf 23`, no audio:

| Chain | Wall time |
|---|---:|
| No filter | 444 ms |
| `eq=saturation=1.08` | 539 ms |
| Global `colorlevels` + `eq` | 727 ms |
| Global `colorlevels` + `eq` + `unsharp` | 911 ms |

The global transform adds about 0.28 s per second of 4K output on this host
relative to no filter in this synthetic benchmark. Real encoder settings and
hardware will change the ratio; this is an order-of-magnitude check, not a
release promise.

Python/OpenCV dark-channel reference (not an export pipeline):

| Resolution | Time per frame |
|---|---:|
| 1280x720 | 121 ms |
| 3840x2160 | 1285 ms |

A 30 s 4K clip at 30 fps would spend roughly 20 minutes in the reference
algorithm alone before decode/encode. That is not viable for the current
interactive export path.

## 6. Recommended bounded V1

Only if PM, UX, and CTO approve it after real-fixture validation:

- **One `Dehaze` slider**, 0-100, neutral 0. No extra hue/sky controls in V1.
- Use **global atmospheric-light subtraction** with a bounded transmission floor
  (for example `t_min = 0.5`), implemented with per-channel `colorlevels` and
  a restrained saturation compensation. No per-pixel local transmission.
- Estimate the atmospheric light deterministically from a small, documented
  sample of frames per clip. The same sampler must feed preview stills and
  export. Define and test the sampling contract before coding the UI.
- Place Dehaze **before** the existing creative image grade and LUT so the
  user's exposure/contrast controls operate on the dehazed image. Record the
  order in an ADR and test it against LUT/color-animation combinations.
- Use the existing preview-still path for paused/scrub parity. Continuous
  playback may use a per-channel linear SVG component transfer if it can be
  proven equivalent enough; otherwise keep the existing honesty chip and do not
  claim full-motion LUT+dehaze parity.
- Support photos through the same grade chain if the parity and export tests
  pass without a separate implementation.
- Keep existing static grades, LUTs, color animation, saturation ramps,
  sharpen/denoise, and projects compatible.
- Preserve Undo/Redo, project save/reopen, and source media. No source changes.

### 6.1 Explicit non-scope

- Per-pixel dark-channel dehaze, local transmission maps, or guided filtering
  in the V1 slider.
- Sky replacement, generative fill, AI enhancement, or cloud processing.
- Automatic per-scene dehaze or auto white balance.
- Separate controls for haze color, depth, or sky protection.
- Changes to the SQLite schema. `effect_settings` may gain a validated nested
  value only with an ADR and migration/validation plan.

## 7. Acceptance criteria for a follow-up issue

- Before/after samples from the **same** real hazy aerial source frame, compared
  against the existing contrast/highlights/shadows/blacks controls.
- Demonstrable improvement on the agreed haze fixtures without unacceptable
  halos, noise amplification, or sky color shifts; failure cases documented.
- Neutral default leaves existing projects pixel-identical.
- Paused/scrub preview and MP4 export match within documented tolerances for
  start/middle/end and for clips that also use a LUT, HSL, wheels, color
  animation, or a saturation ramp.
- Trimming, splitting, speed, transitions, loops, Undo/Redo, and project reload
  keep the intended result.
- Audio synchronization is unchanged.
- Performance measured on 1080p and 4K, including the packaged Windows EXE.
- Real Windows WebView2 GUI evidence for the slider, preview states, save/reopen,
  and export.
- DE/EN strings and user-facing docs explain what Dehaze does and does not
  recover.

## 8. Recommendation

**GO for a bounded global Dehaze strength control**, pending real aerial haze
fixtures and the normal PM/UX/CTO gates. The probe shows that a cheap
FFmpeg-native global transform can outperform naive manual contrast on a
controlled synthetic scene, and it fits the existing export/preview still
architecture.

**NO-GO for a per-pixel dark-channel dehaze in the current architecture.** It
needs a separate rendering/filter decision, a large dependency or custom filter,
and a preview-parity investigation. It should not be disguised as a simple
slider.

**No code is added by this discovery PR.** The probe used an environment-local
OpenCV install only as a quality reference; OpenCV is not a project dependency
and must not be assumed in production.

## 9. Limitations

- The fixture is synthetic, not real drone footage. Atmospheric haze, sky
  gradients, water reflections, foliage, and sensor noise can change both
  quality and cost.
- PSNR and SSIM reward similarity to a synthetic clean reference; they are not
  evidence of a good-looking grade. Human review on real footage is required.
- No packaged Windows EXE and no real WebView2 GUI session were used. The
  preview-parity statements are engineering assessments.
- 4K timing is a single-host, CPU-only, ultrafast-encoder benchmark. Hardware
  encoders and real encoder settings change the ratio.
- The bundled FFmpeg 7.1 build has no `defog` or `frei0r` dehaze filter.
- This document does not approve product scope, UX, architecture, or release.
