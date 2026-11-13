# Color Workspace execution checkpoint

Updated: 2026-11-13. Integration branch `develop` tip
`8f4cbc8edab5740b40f80032587f10cd25037231`.

A merged PR is not full issue acceptance. This file records shipped slices vs
remaining gaps after the PO complete-Color-Workspace directive.

## Merged develop PRs (this cycle)

| PR | Merge SHA | Slice |
|---|---|---|
| #412 | (Phase 1 packaged E2E) | Packaged Windows WebView2 journey extensions |
| #413 | (on develop) | #351 write-enable + safeguards |
| #414 | (on develop) | Kelvin/tint mappings |
| #417 | `611711f…` | Managed primaries UI |
| #418 | `0ec002b…` | Managed lut bake preview/export |
| #420 | `c7e1859…` | Wheels + managed HSL UI |
| #419 | `11bd8ea…` | Seven curve families UI |
| #421 | `c3eabdc…` | Mask/qualifier apply + UI; photo spatial; video fail-closed |
| #422 | `8f4cbc8…` | Creative LUT resolve/bake/UI |

Final `develop` SHA for this checkpoint: `71936cebac9db4dab850c053bc82aeecfbd640fa`
(includes Color Workspace feature merges through `#422` plus checkpoint docs `#423`).

## Feature matrix (honest)

| Capability | Status | Evidence |
|---|---|---|
| Canonical grade + writes after safeguards | Available now (managed) | #413 + grade routes |
| Primaries (exposure…whites, Kelvin/tint) | Available now | UI + bake + unit vectors |
| Seven curve families | Available now | UI + bake |
| Wheels Lift/Gamma/Gain/Offset + managed HSL | Available now | UI + bake; zero-value preserved |
| Linear/radial/brush selection eval | Available now (math + UI presets) | #421; brush strokes are preset not viewer painting |
| Qualifiers RGB/HSL/luma | Available now (math + UI presets) | #421; eyedropper accept-to-range UI still open |
| Creative .cube LUT strength enable/clear | Available now | #422; confined assets + digest cache |
| Preview/export pointwise bake | Available now | lut3d bake |
| Spatial photo preview/export | Available now | CPU path; JPEG-boundary preview limitation |
| Spatial video export | Fail-closed | Needs timing/audio-accurate adapter |
| Playback proxy spatial/managed LUT | Gap | Proxy path not fully wired for all managed cases |
| GPU WebGL managed adapter (#360) | Later | Not shipped |
| Scopes tap (#362/#366) | Partial fixtures | Live tap depends on #359 plane |
| Packaged regression E2E (tip `71936ceb`) | PASS (local) | All journeys in `windows_e2e.py` ok incl. transitions, 1080p, lut_parity; evidence `tmp-packaged-e2e-color/run-71936ceb/` |
| Source-app Creative/Pro workspace journey | PASS | `packaging/e2e/studio_color_workspace.py` |
| Managed convert→curves→masks→LUT packaged journey | NOT_RUN | Needs dedicated CDP steps beyond Creative/Pro smoke |
| Full #365 acceptance matrix | OPEN | Synthetic harness + managed-grade packaged evidence pending |

## Open Color Workspace issues

Do not close foundations as complete user-facing features without AC evidence.

| Issue | After this cycle | Remaining |
|---|---|---|
| #351 | Writes enabled with safeguards | Confirm recovery/backup AC comments; PO close |
| #352 | Creative LUT wired | Technical conversion UX/once gate polish; parity gate |
| #353 | Primaries UI+bake | PO acceptance; packaged evidence |
| #354 | Curves UI+bake | PO acceptance |
| #355 | Wheels/HSL UI+bake | PO acceptance |
| #356 | Mask apply+UI | Video spatial; orientation/DPR fixtures; viewer handles |
| #357 | Qualifier apply+UI | Eyedropper accept-to-range |
| #358 | Animation clocks | Still unsupported (fail-closed) |
| #359 | FFmpeg/CPU adapters | Bake shipped; spatial video + proxy gaps |
| #360 | GPU adapter | Open |
| #361 | Creative/Pro workspace | Large UI slice landed; serial step editor incomplete |
| #362/#366 | Scopes | Open |
| #363 | Shared actions/bridge | Partial |
| #364/#365 | Parity harness / final matrix | Open |

## Exact next tasks

1. Packaged Windows WebView2 retest on tip `8f4cbc8` covering convert→primaries→curves→wheels→selection (photo)→creative LUT→720p/1080p export.
2. Issue cleanup comments with evidence; close only when AC fully met.
3. Video spatial adapter or keep documented fail-closed.
4. Eyedropper accept path (#357 remainder).
5. Do not merge to `main` or publish a release.
