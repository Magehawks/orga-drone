# Color Workspace — control ↔ engine mapping

Product slice for the Studio **Image** inspector (Creative / Pro views).
Both views edit the same per-clip grade. Mode choice is a local UI preference
only (`localStorage`); it is never stored in the project.

## Shipped controls (engine available)

| UI control | Creative | Pro | Persistence | Preview / export contract | Primary modules |
|---|---|---|---|---|---|
| Quick Looks | yes | yes | `effect_settings.image` + `quick_look` | Shared grade still + export | `studio_looks.py`, `/look` |
| Brightness / contrast / saturation / warmth | yes | yes | `effect_settings.image` | Shared path | `studio_image.py`, `/image` |
| Hold to compare (before/after) | yes | yes | none (preview only) | `preview-frame?before=1`; keeps technical conversion | `studio/color-compare.js` |
| Reset adjustments | yes | yes | clears basic + tonal; look label clears | Same save path | `studio.js` + `/image` |
| Convert camera profile (D-Log M) | yes | yes | `effect_settings.color` | LUT still / proxy / export | `studio_lut.py`, `/color` |
| Creative `.cube` look + strength | yes | yes | `effect_settings.color` | LUT still / proxy / export | `studio_lut.py`, `/color` |
| HSL mixer (8 ranges) | hidden | yes | `effect_settings.hsl` | Generated LUT on shared path; playback may omit | `studio_hsl.py`, `/hsl` |
| Color wheels (shadows / midtones / highlights) | hidden | yes | `effect_settings.color_wheels` | Generated LUT on shared path; playback may omit | `studio_color_wheels.py`, `/color-wheels` |
| Fine-tune tonals | hidden | yes | `effect_settings.image` | Restrained; no clipped recovery | `studio_image.py` |
| Sharpen / denoise | hidden | yes | `effect_settings.detail` | Preview approximates | `studio_detail.py`, `/detail` |
| To black and white (video) | hidden | yes | saturation ramp | Preview approximates | `studio_image.py` |
| Color points / LUT strength animation | Effects tab | Effects tab | `effect_settings` color animation | Pause/scrub stills | `studio_color_animation.py` |
| Privacy masks (blur / pixelate) | Effects tab | Effects tab | `effect_settings.masks` | Preview matches export | `studio_mask.py` |

Shared contracts: [`docs/architecture/STUDIO_ACTIONS.md`](../architecture/STUDIO_ACTIONS.md),
[`docs/STUDIO_MODULES.md`](../STUDIO_MODULES.md), ADRs 0011 / 0027–0030.

## Not in this UI (Later / no engine yet)

These appear in some product briefs as Color Workspace tools. They are **not**
shipped and must not be exposed as working controls:

| Requested tool | Status | Why blocked |
|---|---|---|
| RGB / luma curves | **Later** (`PRODUCT_VISION.md`) | No curve model, API, or filter-graph owner |
| Scopes (waveform / parade / vectorscope) | Optional follow-up in closed #176; not accepted | No trustworthy histogram sampling; educational fakes would mislead |
| Color qualifier / secondary keyer | Absent | No qualifier engine; HSL ranges are the shipped selective tool |
| Node graph | Absent | No node graph model; Studio stays accordion inspectors |
| Sky / freeform color masks | **Later** | Privacy rectangles exist under Effects; not a color keyer |
| Local Dehaze | Discovery #302 | Engine not approved for Image inspector |

Engine work for the rows above belongs to separate Codex/engine issues. UI PRs
must not invent endpoints or mock “live” scopes/curves.

## Mode contract

| Mode | Shows | Hides | Shared grade? |
|---|---|---|---|
| Creative | Camera profile, Quick Looks, four sliders, compare, resets | HSL, wheels, Fine-tune (incl. B&W ramp) | yes |
| Pro | Everything Creative plus HSL, wheels, Fine-tune | nothing shipped | yes |

Legacy preference values `standard` / `expert` map to `creative` / `pro` on
read so existing browser profiles keep their choice.
