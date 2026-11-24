# Acceptance matrix: local tracking, Subject Focus, portrait reframe (#298–#300)

Status: **discovery closeout**. No Studio tracking UI, Subject Focus effect, or
portrait auto-reframe product code is added by this document. Product status in
`docs/PRODUCT_VISION.md` stays unchanged: tracking remains **Later**.

Pinned tree: `origin/develop` at `ed22c9d` (2026-11-24).

Related discovery: [`298-motion-tracking-research.md`](298-motion-tracking-research.md),
[`298-tracking-spike.md`](298-tracking-spike.md). Merged evidence PRs: #305, #402.

## 1. Classification

| Issue | Title | Classification | Evidence | Product action |
|---|---|---|---|---|
| #298 | Reusable local motion tracking | **Completed discovery** | Research + synthetic LK spike; packaging note | Recommend PO close as discovery NO-GO for a 2.4.0 shipping tracker |
| #299 | Subject Focus | **Blocked by product / architecture** | Depends on shared tracked-mask foundation that is not approved to ship | Keep open; do not implement |
| #300 | Portrait auto-reframe 9:16 | **Blocked by product / architecture** | Same tracking dependency; issue asks for manual-keyframe validation before auto-follow | Keep open; reuse existing zoom/pan (#86 / ADR 0018); do not add a second crop model |

## 2. Acceptance matrix (binding)

| Criterion | #298 research | #298 spike | #299 | #300 |
|---|---|---|---|---|
| Manual target selection defined | PASS (box contract) | PASS (synthetic box) | BLOCKED | BLOCKED |
| Explicit lost-target (no silent success) | PASS (design) | PASS (occlusion reports lost) | BLOCKED | BLOCKED |
| Shared track contract for consumers | PASS (proposed, not implemented) | N/A | BLOCKED | BLOCKED |
| Preview/export moving-mask parity | NOT_RUN | NOT_RUN | BLOCKED | BLOCKED |
| Real drone footage | NOT_RUN | NOT_RUN | BLOCKED | BLOCKED |
| Packaged Windows WebView2 E2E | NOT_RUN (discovery) | NOT_RUN | NOT_RUN | NOT_RUN |
| Product UI / DE–EN strings | Out of scope | Out of scope | Not approved | Not approved |
| Source media unmodified | PASS (read-only probes) | PASS | — | — |

## 3. Shared motion-tracking capability (one engine)

Future work, if the Product Owner approves a new implementation issue, must reuse
**one** local track primitive for masks, Subject Focus, overlays, and reframe:

- manual normalized box; clip-local source time;
- samples with explicit `lost` / confidence;
- manual correction, stop, and re-track;
- one resolver for preview and export;
- no cloud inference; do not label classical CV as AI;
- do not reuse DJI `track_json` telemetry as picture tracking.

Do **not** create separate trackers per feature.

OpenCV (`opencv-python-headless`) is now a project dependency for spatial mask
raster work. That does **not** approve a shipping motion tracker, CSRT/contrib
trackers, downloaded models, or Subject Focus UI. Spike still shows scale drift
without an honest lost signal.

## 4. #299 Subject Focus

Blocked until a separately approved tracked rectangular mask foundation ships
with measured preview/export parity. Existing privacy masks remain static
rectangles. Do not invent depth-of-field or AI segmentation.

## 5. #300 Portrait reframe

Blocked for automatic subject following until the shared track foundation is
approved. Existing per-clip zoom/pan (ADR 0018) already covers static crop and
two-point motion; do not add a parallel crop model. A multi-keyframe manual
portrait workflow needs its own product approval before coding.

## 6. Close recommendations

| Issue | Recommend | Who | Notes |
|---|---|---|---|
| #298 | **Close as completed discovery** after PO accepts the NO-GO | Product Owner | Comment: discovery complete; no shipping tracker in current milestone |
| #299 | **Leave open** | — | Blocked on approved tracking foundation + UX |
| #300 | **Leave open** | — | Blocked; prefer extending framing after product approval |

Agents must not close issues without Product Owner authorization.

## 7. Follow-up only after PO approval

A future implementation issue would need: ADR for track storage, packaging size
measurement, moving-mask preview/export parity, WebView2 E2E, and real-footage
validation. Until then: no tracker UI, no Subject Focus, no auto-reframe.
