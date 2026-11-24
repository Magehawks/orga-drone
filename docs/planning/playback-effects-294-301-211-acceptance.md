# Playback and effect consistency — acceptance matrix (#294 / #301 / #211)

Pinned baseline: `origin/develop` at `572d6e6` (post #569 / `411c6cc`, 2026-11-24).
Branch: `feat/playback-effects-complete-211-294-301`.
Related merges: #376 (294 Phase A), #569 (294 Phase B), #401 (301 batch-1),
#213–#217 / #306 / #342 / #368 (211), #431 / #436 / #443 (358 clocks).

This matrix separates **Available now** from **open gates**. Discovery
recommendations that were not separately authorized stay blocked. Thresholds
are not weakened.

## Infrastructure vs creator-facing animated grading

| Layer | What it is | Status |
|---|---|---|
| Animation *infrastructure* (#358 / #431 / #436 / #443) | Canonical grade clocks, story-local export anchors | On develop |
| Creator-facing animated grading (#211) | Color bar, Automatic presets / Manual points, LUT strength | On develop; packaged WebView2 `.cube` journey still NOT_RUN |

## Shared-file ownership (parallel workstreams)

| File / area | This PR | Do not race |
|---|---|---|
| Forward-loop proxy tests, gate registration, mutation targets | Owner | Color Workspace / Masking / Collage |
| `studio_transition.py`, encoder xfade map | Verify only (#401) | Color / Masking |
| `studio_color_animation.py` | Verify / interpolation mutation only | Color Workspace |
| `studio.js` | No clock rewrite in this closeout | Coordinate if touching shared grade apply |

## #294 — Color-accurate HSL/LUT preview for forward-loop clips

| Criterion | Status | Evidence / note |
|---|---|---|
| Phase A: truthful loop-cause chips when no proxy | **Implemented** | PR #376 |
| Phase B: reuse existing FFmpeg playback proxy | **Implemented** | PR #569 |
| Phase B: proxy-local seek/wrap/overlap mapping | **Implemented** | `proxy-loop-map.js` |
| Phase B: non-zero source in-point + section repeats | **Regression added** | `test_nonzero_source_in_section_repeat_builds_proxy_from_cut_in` |
| Phase B: decoded-frame still↔proxy parity (synthetic) | **PASS** | mean RGB channel error &lt; 8/255 |
| Phase B: Windows WebView2 EXE (synthetic media journeys) | **Executed PASS** (matrix Layer-4 stays NOT_RUN) | `docs/discovery/playback-effects-packaged-e2e-20261124.md` |
| Phase B: real drone footage WebView2 | **NOT_RUN** | Private media; not claimed |
| Proxy never becomes export source | **Preserved** | Export uses library `media_path` only |
| Fail-closed: animated color / speed≠1 / clip audio | **By design** | Proxy ineligible; chips remain truthful |

## #301 — Drone-friendly transition pack

| Criterion | Status | Evidence / note |
|---|---|---|
| Discovery + batch-1 (`blur_dissolve` + soft wipes) | **Implemented on develop** | #401; ADR 0010 |
| Export xfade id stability | **Regression contract** | `test_contract_301_xfade_ids_are_native_and_stable` |
| Packaged WebView2 creative persistence | **Executed PASS** (matrix Layer-4 stays NOT_RUN) | `timeline_transitions` persisted blur_dissolve + soft_wipe_left |
| Packaged soft-wipe / blur pixel-parity | **NOT_RUN / prior NO-GO** | ADR: preview may approximate; PO closeout pending |
| Whip / luma / zoom-spin / motion-match | **Blocked** | Discovery NO-GO; normalize → `cut`; no silent expansion |

### Unsupported transition technical limitations (do not implement without architecture approval)

| Type | Limitation |
|---|---|
| Whip pan | Needs motion-estimated intermediate frames / directional blur field; CSS/xfade cannot reproduce aerial whip without a new renderer |
| True luma wipe | Requires luminance-keyed wipe from footage; FFmpeg `smooth*` is geometric soft wipe, not luma-driven |
| Zoom / spin | Needs animated transform + motion blur across overlap; not expressible as stable xfade id without new filter graph + preview parity plan |
| Motion match | Needs feature tracking between outgoing/incoming clips; out of Studio transition model |

## #211 — Animated color grading

| Criterion | Status | Evidence / note |
|---|---|---|
| Automatic presets + Manual points + LUT strength | **Implemented on develop** | #215–#217 et al. |
| Deterministic keyframe interpolation | **Contract + mutation** | `test_contract_211_*` / `broken_keyframe_interpolation` |
| Persistence / Undo-Redo | **Implemented** | Existing history suites |
| Packaged WebView2 GUI E2E with synthetic `.cube` | **Executed PASS** (matrix Layer-4 stays NOT_RUN) | `lut_parity` journey in packaged evidence |
| User-provided private `.cube` on real drone | **NOT_RUN** | No private media committed |
| Original AC: grade A→B between two saved looks | **Not in shipped Vision V1** | Leave open / do not fake |
| Animated highlights/shadows/blacks | **Out of ColorKey V1** | Documented; no silent expansion |

## Creator Regression Gates registration

Registered in existing harness only (no duplicate runner):

- `tests/fixtures/regression_gate_modules.json` — modules + lean gate nodes + mutation targets
- `tests/fixtures/regression_coverage_matrix.json` — suites on `video-editing-playback` / `transitions-effects`
- Mutation targets: `broken_loop_mapping`, `broken_keyframe_interpolation` (plus existing clip targeting / transition timing)

## Explicit blockers requiring product decisions

1. **#301 closeout:** PO must accept #401 preview approximation + optional packaged evidence, or approve a new parity plan. No new transition types without a new issue.
2. **#211 closeout:** Packaged WebView2 interaction + decoded frames with a user `.cube`.
3. **#294 real-footage EXE:** Synthetic decoded-frame parity is automated; real drone WebView2 remains a packaged/manual gate.

## Non-goals in this branch

- Additional transition types beyond #401.
- New animated-grading UI / graph editor / second animation engine.
- Studio redesign / framework migration / AI claims.
- Self-merge, main merge, or release.
