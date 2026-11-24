# Playback and effect consistency — acceptance matrix (#294 / #301 / #211)

Pinned baseline: `origin/develop` at `ed22c9d` (2026-11-24).
Branch: `feat/playback-effects-294-301-211`.
Related merges: #376 (294 Phase A), #401 (301 batch-1), #213–#217 / #306 / #342 / #368 (211),
#431 / #436 / #443 (358 clocks / story-local grading).

This matrix separates **Available now** (on develop + this PR) from **open gates**.
Discovery recommendations that were not separately authorized stay blocked.

## Infrastructure vs creator-facing animated grading

| Layer | What it is | Status |
|---|---|---|
| Animation *infrastructure* (#358 / #431 / #436 / #443) | Canonical grade clocks, story-local export anchors, RenderContext helpers | On develop |
| Creator-facing animated grading (#211) | Color bar, Vorlagen/Manuell, up to 8 linear points, LUT strength presets | On develop; packaged WebView2 `.cube` journey still pending (#317) |

## Shared-file ownership (parallel workstreams)

| File / area | This PR | Do not race |
|---|---|---|
| `studio_playback_proxy.py`, `proxy-policy.js`, `proxy-loop-map.js`, forward-loop proxy tests | #294 Phase B owner | Color Workspace / Masking / Collage |
| `studio_transition.py`, `transition-pack.js`, encoder xfade map | Verify only (#301 already shipped in #401) | Color / Masking |
| `studio_color_animation.py` | Verify / regression contract only | Color Workspace |
| `studio.js` seek/wrap paths | Additive proxy-local mapping only (no second clock engine) | Coordinate if touching shared grade apply |

## #294 — Color-accurate HSL/LUT preview for forward-loop clips

| Criterion | Status | Evidence / note |
|---|---|---|
| Phase A: truthful loop-cause chips when no proxy | **Implemented** | PR #376; retained for preparing/miss |
| Phase B: reuse existing FFmpeg playback proxy (no second HSL/WebGL engine) | **Implemented (this PR)** | Eligibility allows loops/repeats; one graded cycle |
| Phase B: proxy-local seek/wrap/overlap mapping | **Implemented (this PR)** | `proxy-loop-map.js` + studio.js wrap/seek call sites |
| Phase B: A/V sync proxy-relative | **Implemented (reuse)** | Existing LUT-proxy audio path; wraps keep proxy `currentTime` |
| Phase B: decoded-frame still↔proxy parity | **Implemented (synthetic)** | `test_forward_loop_proxy_decoded_frame_matches_preview_still` |
| Phase B: Windows WebView2 EXE with real drone footage | **NOT_RUN** | Needs packaged EXE + private media; not claimed |
| Normal non-loop playback / export unchanged | **Preserved** | Existing suites |

**Architecture note:** Checkpoint 240 warned against a playback-clock *rewrite*. This PR adds a small pure mapper and routes existing wrap seeks through it; it does not invent a second animation engine.

## #301 — Drone-friendly transition pack

| Criterion | Status | Evidence / note |
|---|---|---|
| Discovery + batch-1 (`blur_dissolve` + soft wipes) | **Implemented on develop** | #401; ADR 0010 |
| Export xfade id stability | **Regression contract** | `test_contract_301_xfade_ids_are_native_and_stable` |
| Packaged WebView2 pixel-parity claim | **NOT_RUN / prior NO-GO** | Soft-wipe packaged gate failed historically; ADR: preview approximates |
| Whip / luma / zoom-spin / motion-match | **Blocked** | Discovery NO-GO; no silent feature expansion |

## #211 — Animated color grading

| Criterion | Status | Evidence / note |
|---|---|---|
| Creator-facing Auto/Manual color points + LUT strength | **Implemented on develop** | #215–#217 et al. |
| Deterministic keyframe interpolation | **Regression contract** | `test_contract_211_keyframe_interpolation_is_deterministic` |
| Packaged WebView2 GUI E2E with user `.cube` | **NOT_RUN / blocked on #317** | Do not invent substitute evidence |

## Explicit blockers requiring product decisions

1. **#301 closeout:** PO must accept #401 approximation + optional packaged evidence, or approve a new parity plan. No new transition types without a new issue.
2. **#211 closeout:** Packaged WebView2 interaction + decoded frames with a user `.cube` (#317). Keep issue open until that gate lands.
3. **#294 real-footage EXE:** Synthetic decoded-frame parity is automated; real drone WebView2 remains a manual/packaged gate.

## Non-goals in this branch

- Additional transition types beyond #401.
- New animated-grading UI / graph editor / second animation engine.
- Studio redesign / framework migration / AI claims.
- Self-merge, main merge, or release.
