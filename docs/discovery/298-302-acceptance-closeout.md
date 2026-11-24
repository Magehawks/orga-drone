# Tracking and Advanced Creator Tools — acceptance close-out (#298–#302)

Status: **discovery close-out only**. This document classifies issues
#298, #299, #300, and #302 against merged discovery evidence on
`origin/develop` at `ed22c9d` (2026-11-24 audit). It does **not** ship a
tracker, Subject Focus, portrait auto-reframe, or Dehaze control.

Pinned tree: `origin/develop` @ `ed22c9d3037fb935d5a453d032aaf70d471235fb`.
Worktree: `C:\Users\Niwes\.cursor\worktrees\orga-drone\tracking-298-302`
Branch: `docs/tracking-298-302-closeout`

## 1. Classification

| Issue | Title | Classification | Shipping status |
|---|---|---|---|
| #298 | Reusable local motion tracking | **Completed discovery** | NO-GO for a production tracking editor in 2.4.0 |
| #299 | Subject Focus | **Blocked by product / architecture** | Blocked on an approved shared tracking foundation |
| #300 | Portrait auto-reframe (9:16) | **Blocked by product / architecture** (auto-follow); manual framing already exists | Auto subject-follow blocked on #298; do not add a second crop model |
| #302 | Local Dehaze | **Completed discovery** | NO-GO for a Dehaze slider in the current FFmpeg-only pipeline |

Approved implementation scope for this pass: **none**. Unapproved discovery
proposals were not implemented.

## 2. Acceptance matrix

| Criterion | #298 | #299 | #300 | #302 | Evidence / result |
|---|---|---|---|---|---|
| Discovery docs merged | PASS | n/a (feature) | n/a (feature) | PASS | #305+#402; #304+#309 |
| GO/NO-GO recorded | PASS (NO-GO ship) | BLOCKED | BLOCKED | PASS (NO-GO ship) | Spike + validation docs |
| Shared motion-tracking engine | NOT shipped | depends | depends | n/a | No `studio_tracking*` module |
| Subject identity + manual correction | Spike-only (synthetic) | BLOCKED | BLOCKED | n/a | Spike lost-state measured; no product UI |
| Honest tracking-loss handling | Spike PASS (synthetic) | BLOCKED | BLOCKED | n/a | Forward-backward lost at occlusion |
| Subject focus + background blur | OUT | BLOCKED | n/a | n/a | Requires tracked mask foundation |
| 9:16 portrait reframing (tracked) | n/a | n/a | BLOCKED | n/a | Manual Ken Burns already in `studio_frame.py` |
| Dehaze within approved operator contract | n/a | n/a | n/a | NO-GO | Real fixtures superseded synthetic GO |
| Local, non-destructive | PASS (docs only) | BLOCKED | Existing manual frame PASS | PASS (docs only) | No source media writes |
| Preview/export product parity | NOT_RUN (no product) | NOT_RUN | Manual frame only | NOT_RUN | No fake product E2E |
| Packaged Windows WebView2 E2E | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | Discovery-only; no shipping UI |
| Real footage / real haze fixtures | NOT_RUN (#298) | — | — | PASS (private local; not committed) | Validation measurements committed |
| CI deterministic discovery regressions | PASS (when cv2 present) | — | — | PASS | `test_tracking_spike.py`, `test_dehaze_benchmark.py` |

## 3. Evidence already on develop

### #298 — motion tracking

| Artifact | Role |
|---|---|
| [`298-motion-tracking-research.md`](298-motion-tracking-research.md) | Research; conditional GO for a bounded spike; NO-GO for #299/#300 until foundation passes |
| [`298-tracking-spike.md`](298-tracking-spike.md) | Synthetic LK spike; **NO-GO** for production tracker in 2.4.0 |
| `tests/test_tracking_spike.py` | Deterministic synthetic geometry / lost-state / scale-drift cases |
| PR [#305](https://github.com/Magehawks/orga-drone/pull/305), [#402](https://github.com/Magehawks/orga-drone/pull/402) | Merged discovery |

Spike measurements (synthetic 96×128, 16 frames):

| Case | Result |
|---|---|
| 4 px/frame translation | Center error 0 px |
| Marker removed after frame 8 | Lost reported; no silent slide |
| Marker grows in place | Never lost; center error 5 px (silent drift) |

Real footage, 1080p timing, packaged EXE: **NOT_RUN**.

PO on #402 (2026-11-13): spike accepted as discovery evidence, not a shipping
tracker. Do not add tracking UI as a consequence of the spike.

### #302 — dehaze

| Artifact | Role |
|---|---|
| [`302-local-dehaze.md`](302-local-dehaze.md) | Synthetic probe (later superseded) |
| [`302-local-dehaze-validation.md`](302-local-dehaze-validation.md) | Real-fixture **NO-GO** |
| [`302-local-dehaze-benchmark.py`](302-local-dehaze-benchmark.py) / measurements JSON | Reproducible research fixtures |
| `tests/test_dehaze_benchmark.py` | Deterministic math / neutral / boundary checks |
| PR [#304](https://github.com/Magehawks/orga-drone/pull/304), [#309](https://github.com/Magehawks/orga-drone/pull/309) | Merged discovery |

Quality/latency notes from validation (committed, anonymised):

- Synthetic global 50–100% improved PSNR/SSIM vs hazy input.
- Real clear/sunset/bright-cloud scenes: over-darkening / shadow crush; estimator fragile.
- Atmosphere sampling intended for ≤640 px long edge; 4K full-frame dark-channel remains out of scope.
- FFmpeg `colorlevels` mapping matched Python within ~0.4/255 on synthetic RGB.
- Playback/preview parity for a product slider: **NOT_RUN** (no product control).

### #299 / #300 — dependents

No discovery implementation PRs. Checkpoint correctly waits on #298.
Existing manual zoom/pan framing (`studio_frame.py`, ADR 0018) is **not**
subject tracking and must not be duplicated as a second crop model.

## 4. Parallel-workstream ownership

| Concern | Owner | Rule |
|---|---|---|
| Privacy masks / on-canvas mask edit / object-selection | Masking workstream (#535 and related) | Selection engine ≠ motion tracker |
| Color Workspace grades / grading mattes | Color Workspace (#351–#366) | No tracking claims; no Dehaze until approved |
| Color scopes | Scopes workstream | Read-only meters; no tracking/dehaze |
| Collage / playback clocks | Collage / Playback agents | Avoid shared Studio export graph edits for tracking |
| Shared local motion tracking (future) | Single foundation only, after PO-approved implementation issue | Do **not** create per-feature trackers for Focus, Reframe, overlays, or removal |

OpenCV (`opencv-python-headless`) may appear on `develop` for other approved
local CV uses (for example object-selection). That dependency is **not**
authorization to ship a Studio motion-tracking editor, package a separate
tracking stack, or reopen #298 as a feature without a new PO-approved issue.

## 5. Explicit product blockers

1. **No approved production tracking contract** (schema/ADR, preview/export
   parity, packaging budget, lost-state UX) after the #298 NO-GO.
2. **#299 and tracked #300** require that foundation; starting them now would
   invent capabilities absent from the approved tree.
3. **#302** FFmpeg-only global veil subtraction is NO-GO on real fixtures;
   any future Dehaze needs a separately approved R&D/implementation issue with
   a robust multi-frame atmosphere path and preview/playback/export proof.
4. Automatic person/object detection, cloud inference, and generative fill
   remain out of product scope (`PRODUCT_VISION.md` / issue out-of-scope).

## 6. Close recommendations (honest)

| Issue | Recommendation | Rationale |
|---|---|---|
| #298 | **Close as completed discovery (NO-GO ship)** after PO acknowledges this close-out | Research + spike merged; shipping tracker explicitly rejected for 2.4.0 |
| #302 | **Close as completed discovery (NO-GO ship)** after PO acknowledges this close-out | Validation superseded synthetic GO; no approved operator contract remains |
| #299 | **Keep open**, marked blocked / Later | Implementation issue; blocked until a future approved tracking foundation |
| #300 | **Keep open**, split mentally: manual framing available; tracked follow blocked | Do not close as “done”; do not implement auto-follow now |

Optional later (only if PO asks; not this PR):

- Manual mask keyframe interpolation on the existing normalized privacy box
  (`studio_mask.py`) without a tracker.
- New implementation issues for a bounded tracking foundation and/or a
  non-FFmpeg-only Dehaze R&D slice, each with ADR + packaging + parity gates.

## 7. What this PR changes

- Adds this close-out matrix and ownership notes.
- Updates `docs/planning/execution-checkpoint-240.md` rows for #298–#302.
- Does **not** add Studio UI, Control API actions, `effect_settings` keys,
  export filters, or cloud services.

## 8. Test plan for this close-out

- [x] Re-read #298/#299/#300/#302 and merged discovery PRs on pinned develop.
- [x] `pytest tests/test_tracking_spike.py tests/test_dehaze_benchmark.py -q` — **11 passed** locally (OpenCV 4.9.0, 2026-11-24)
- [x] Document PASS / FAIL / NOT_RUN (no fake product WebView2 E2E):
  - Unit/discovery regressions: **PASS** (11)
  - Real footage tracking: **NOT_RUN**
  - Product WebView2 E2E (tracker/focus/reframe/dehaze UI): **NOT_RUN** (no shipping UI)
  - Packaged EXE: **NOT_RUN**
