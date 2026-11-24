# Acceptance closeout: #298 / #299 / #300 / #302

Independent audit on `origin/develop` at `ed22c9d` (2026-11-24). This document
is discovery closeout only. It does **not** ship a tracker, Subject Focus,
portrait auto-reframe, or Dehaze control.

Detailed matrices:

- Tracking / Subject Focus / portrait: [`298-299-300-acceptance-matrix.md`](298-299-300-acceptance-matrix.md)
- Dehaze: [`302-closeout.md`](302-closeout.md)

Merged evidence already on develop: #305 / #402 (tracking), #304 / #309 (dehaze).

## Classification

| Issue | Classification | Ship? | Close recommendation |
|---|---|---|---|
| #298 | Completed discovery | NO-GO production tracker (current milestone) | Close discovery after PO ack |
| #299 | Blocked by product / architecture | Not approved | Keep open |
| #300 | Blocked for tracked follow; manual frame exists (ADR 0018) | Auto-follow not approved | Keep open |
| #302 | Completed discovery | NO-GO FFmpeg-only Dehaze; not ADR 0035 operator | Close discovery after PO ack |

## Ownership vs parallel workstreams

| Area | Owner for this closeout | Do not conflict with |
|---|---|---|
| Shared motion-track contract (future) | Future PO-approved foundation issue | Masking object-selection, Color Workspace grades |
| Discovery tests `tests/test_tracking_spike.py` | This closeout | Product Studio UI modules |
| Discovery tests `tests/test_dehaze_benchmark.py` | This closeout | Color Workspace operator inventory |
| `docs/planning/execution-checkpoint-240.md` | Combined closeout (resolved) | Other agents editing the same inventory |

OpenCV headless on develop is for spatial mask raster work. It is **not**
authorization to ship Studio motion tracking or Dehaze.

## Product / architecture blockers

1. No approved production tracking ADR / storage / preview-export parity after #298 NO-GO.
2. #299 and tracked #300 require that foundation (one shared engine only).
3. #302 needs a separately approved non-FFmpeg-only path plus ADR 0035 amendment before any slider.
4. Do not invent cloud inference, per-feature trackers, or AI labels for classical CV.

## Quality / performance (prior evidence; re-verified locally)

- Tracking spike: synthetic pan center error ≤3 px; occlusion reports lost; scale keeps a live box with silent center drift (NO-GO reason).
- Dehaze: synthetic PSNR/SSIM improves; real clear/sunset fixtures crush near-black share; timing ~0.28 s/s 1080p and ~1.08 s/s 4K for `colorlevels` (host CPU ultrafast table).
- Product latency/memory paths: **N/A** (no shipping feature).

## Tests

Discovery unit/regression only. Product WebView2 E2E for tracker / focus / reframe / dehaze: **NOT_RUN** (no fake product E2E).

Agents must not close issues without Product Owner authorization. Independent ChatGPT GitHub PR review is required before merge. No self-merge, main merge, or release.
