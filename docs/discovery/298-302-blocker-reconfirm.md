# Blocker reconfirm: #298 / #299 / #300 / #302

Date: 2026-11-24. Tree: `origin/develop` at `572d6e6` plus this discovery
follow-up. Respects merged PR #573 NO-GOs. **No product implementation.**

Prior closeout (binding): [`298-302-acceptance-closeout.md`](298-302-acceptance-closeout.md),
[`298-299-300-acceptance-matrix.md`](298-299-300-acceptance-matrix.md),
[`302-closeout.md`](302-closeout.md).

## 1. Findings vs #573 NO-GOs

| #573 finding | Reconfirm |
|---|---|
| #298 NO-GO production tracker (LK spike; scale silent drift) | **Confirmed.** Pan <=3 px; occlusion reports lost; scale keeps live box with center drift; **new:** in-place rotation reports live success with untracked orientation (false confidence). |
| #299 / tracked #300 blocked on approved shared foundation | **Confirmed.** Foundation still unsuitable; do not implement Subject Focus or auto-reframe. |
| #302 NO-GO FFmpeg-only Dehaze / not ADR 0035 operator | **Confirmed.** Global `colorlevels` crushes dark/clear scenes. Luma-gated shadow-protect softens crush but still alters clear scenes and is not an approved operator. |
| No cloud inference / no per-feature trackers | **Confirmed.** Discovery only; one future contract if PO/architecture approve. |

Re-run: `pytest tests/test_tracking_spike.py tests/test_dehaze_benchmark.py -q` -> all
passed on this host (OpenCV present). Product WebView2 / packaged EXE: **NOT_RUN**.

## 2. Tracking foundation — NO-GO

Smallest offline candidate evaluated: manual box + Lucas-Kanade optical flow +
forward-backward lost check (existing spike). Proposed shared contract remains
the one in the acceptance matrix (manual normalized box; samples with explicit
`lost`/confidence; one preview/export resolver; no cloud; no DJI `track_json`
as picture tracking).

| Blocker | Evidence |
|---|---|
| Scale | Live box, silent center drift (`test_zoom_keeps_a_box_while_the_center_drifts`) |
| Rotation | Live axis-aligned box, no lost, orientation untracked (`test_inplace_rotation_keeps_false_confidence_live_box`) |
| Occlusion | Lost can be reported (`test_occlusion_is_reported_instead_of_a_silent_drift`) — necessary but not sufficient |
| Silent drift / false confidence | Scale + rotation success paths |
| Persistence / preview-export parity | NOT_RUN (no product storage or moving-mask path) |
| Real drone footage / WebView2 / EXE | NOT_RUN |
| Local performance at 1080p/4K | NOT_RUN for product tracker |

**Verdict: NO-GO** for a shipping shared tracking foundation in the current
milestone. Do not start #299 / tracked #300 production work.

Manual multi-keyframe interpolation of the existing mask box remains a possible
*non-tracker* follow-up only with separate PO approval (already noted in the
spike). That is not a motion tracker.

## 3. Dehaze — NO-GO

| Approach | Result |
|---|---|
| Global atmospheric subtraction via FFmpeg `colorlevels` | Synthetic PSNR/SSIM improve; real clear/sunset crush; scene-dependent; does not clearly beat contrast |
| Per-pixel dark-channel transmission | Already NO-GO (architecture / 4K cost) |
| Bounded luma-gated shadow-protect blend (this follow-up) | Reduces near-black share vs raw global crush on a dark synthetic control; **still darkens** relative to source; no haze-vs-clear scene gate; not FFmpeg-filter-graph equivalent without a new path; **not** an ADR 0035 operator |

**Verdict: NO-GO** for a Dehaze slider or grade operator. Do not ship a
misleading control backed by global contrast or unprotected veil subtraction.

## 4. Issue status recommendations

| Issue | Status | Action |
|---|---|---|
| #298 | Completed discovery | PO may **close as discovery NO-GO** after ack |
| #299 | Blocked | **Keep open** until approved foundation |
| #300 | Blocked (auto-follow); manual frame via ADR 0018 | **Keep open** |
| #302 | Completed discovery | PO may **close as discovery NO-GO** after ack |

Agents do not close issues without Product Owner authorization.

## 5. Architecture / PO blockers (precise)

1. **Tracking ADR** for storage shape, lost/confidence semantics, Undo/Redo,
   preview vs export resolver, and packaging cost — required before any Studio
   tracker UI.
2. **Proof** that scale and rotation do not produce silent success (honest lost
   or low-confidence), plus real-footage and WebView2/EXE evidence.
3. **Single engine rule:** masks, overlays, Subject Focus, and reframe share one
   contract; no duplicate trackers.
4. **#299 / #300** need UX approval (Lightroom/DaVinci-style direct selection,
   visible track state, manual correction) only after (1)–(3).
5. **Dehaze** needs a separately approved R&D/implementation issue plus **ADR 0035
   amendment** naming a versioned operator, evaluation domain, stored atmosphere
   or local map, and preview/proxy/export parity — with a scene gate that
   preserves clear/sunset neutrals. Shadow-protect alone is insufficient.
6. Prefer existing exposure/contrast/highlights/shadows/blacks until then.

## 6. Ownership

Touch only discovery docs and `tests/test_tracking_spike.py` /
`tests/test_dehaze_benchmark.py`. Do not conflict with Masking / Color /
Collage / Playback product streams.
