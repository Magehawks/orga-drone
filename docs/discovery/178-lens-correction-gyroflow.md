# Research: Lens distortion correction and optional Gyroflow

- **Issue:** [#178](https://github.com/Magehawks/orga-drone/issues/178)
- **Date:** 2026-10-29
- **Status:** Research / Discovery only. No runtime feature.
- **Depends on:** [#172](https://github.com/Magehawks/orga-drone/issues/172) image-processing architecture (FFmpeg-first)

## Question

Can Orga Drone offer trustworthy local lens correction and optional Gyroflow-style
stabilization for ultra-wide FPV (e.g. Avata 2) without promising results it
cannot deliver, and without breaking MIT packaging or Studio zoom/mask parity?

## Method

Code and packaging review only — no Gyroflow binary was bundled, and no
customer media was committed. Local read-only test folder types (MP4/SRT/LRF/JPG)
were noted for future private spikes; LRF is a preview/proxy sibling, not a
gyro source in this tree.

## Compatibility matrix (honest)

| Input / mode | Lens profile available in-app today | Gyro / IMU usable today | RockSteady / HorizonSteady interaction | Feasibility |
| --- | --- | --- | --- | --- |
| DJI Avata 2 MP4 + SRT (sample shape) | No profile DB; SRT has camera exposure / `color_md`, not lens FOV tables | SRT sample lacked gyro/heading; parser ignores IMU | In-camera already baked into many clips — second correction can crop twice | **No-Go for shipping correction from SRT alone** |
| MP4 without SRT | No | No | Unknown | **No-Go** without user-supplied profile |
| Generic lens undistort (FFmpeg `lenscorrection` / `v360`) | Possible as manual params | N/A | Can fight in-camera stabilize | Spike only; high user skill |
| Gyroflow project / CLI locally | Gyroflow owns profiles | Requires gyro track (often separate / embedded) | Document “already stabilized” warning | **Conditional Go** as **optional external tool**, not in-process |
| Studio zoom/pan + privacy masks | Existing framing after grade | N/A | Extra crop from undistort changes mask coords | Must run **before** frame/masks or remapped |

## License / packaging

| Option | License signal | Windows packaging | Verdict |
| --- | --- | --- | --- |
| FFmpeg filter strings only | Already GPL FFmpeg subprocess ([#172](https://github.com/Magehawks/orga-drone/issues/172)) | No new binary | **Go** for experimental manual undistort spike |
| Bundle Gyroflow | Gyroflow / Qt / deps — separate compliance | Large; MOTW / notices / updates | **No-Go** for MVP bundle |
| “Open in Gyroflow” path launch | User-installed app | Document only | **Go** as documentation / later UX |
| Native lens SDK | Often proprietary | Conflicts with open local-first | **No-Go** |

## Performance

Per-frame optical-flow / gyro stabilize is far heavier than current Studio
grade. Even FFmpeg `lenscorrection` on 4K Avata exports will dominate encode
time. Any future UI must default **off** and warn about extra crop.

## Interactions with Studio today

- Grade → zoom/pan → masks/overlays/HUD/map ([#189](https://github.com/Magehawks/orga-drone/issues/189)).
- Undistort must be an early, optional stage (with [#172](https://github.com/Magehawks/orga-drone/issues/172) filter-order proposal) or masks will drift.
- Preview CSS cannot approximate complex undistort; same parity rule as LUT.

## Go / No-Go

| Proposal | Verdict |
| --- | --- |
| Ship “Objektiv & Stabilisierung” as working controls now | **No-Go** |
| Empty collapsed section in Bild UI promising future tools | **No-Go** (misleading; see [#173](https://github.com/Magehawks/orga-drone/issues/173)) |
| Research spike: manual FFmpeg undistort params on one synthetic clip | **Go** (separate issue, lab only) |
| Optional “Open folder in Gyroflow” / help link | **Go** later under docs (#187), not a Studio effect |
| In-app Gyroflow integration / redistribution | **No-Go** until license + packaging spike passes |

## Follow-up (only if product insists)

1. Private Avata sample matrix (modes with/without RockSteady) — **not** in git.
2. Spike issue: FFmpeg `lenscorrection` preview still vs export crop %.
3. Product copy: never claim stabilization for unsupported footage.

## Non-scope (honored)

Production integration, AI tracking, promising unsupported stabilization.

## Outcome

Research acceptance for #178: compatibility matrix, license/packaging assessment,
and explicit No-Go for shipping Objektiv & Stabilisierung controls now.
