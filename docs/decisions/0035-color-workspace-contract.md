# ADR 0035: Canonical Color Workspace grade and render contracts

- **Status:** Proposed; merging this documentation does not authorize implementation or adopt the model. Explicit Product Owner architecture approval is required.
- **Date:** 2026-11-11
- **Deciders:** Product Owner, following independent review
- **Scope:** [Issue #348](https://github.com/Magehawks/orga-drone/issues/348), Phase A only
- **Baseline:** `origin/develop` at `8ff25454672de14b312e5b9e4d553a9c57d1b8ef`

## Context

The approved product goal is a complete, non-destructive Color Workspace with Creative and Pro modes. This proposal retains primaries, RGB/luma/hue curves, HSL, wheels, qualifiers, eyedroppers, linear/radial/brush masks, LUTs, input/output transforms, serial steps, presets and all four scopes. None becomes available through this PR. Existing product status remains unchanged.

The [contract](../architecture/COLOR_WORKSPACE_CONTRACT.md) specifies proposed semantics, inventory, integration ownership and evidence. The [implementation backlog](../architecture/COLOR_WORKSPACE_BACKLOG.md) specifies separate deliverables and dependencies. These documents are normative parts of this proposal. Existing ADRs 0011, 0019, 0027–0030 remain authoritative for legacy clips. This proposal does not silently supersede their rendered appearance.

Current `effect_settings` is an extensible JSON object in SQLite, not an external project-file format. Legacy image, color, HSL, wheels, detail and animation fields have different readers and consumers. Existing FFmpeg builders are shared, but browser approximations, JPEG stills, early-scaled proxies and MP4 encoding are different numerical pipelines. #320 remains FAIL/BLOCKED_PO_DECISION; its stopped precision experiments are not approved for restoration by #348.

## Decision

### 1. One versioned grade, two explicit evaluation profiles

Propose a `grade` envelope inside existing `effect_settings`; no new SQLite columns are required by this design. New model version 1 has an independent evaluator identifier. `legacy-v1` preserves the current builders, ordering, defaults, animation and output behavior. `managed-sdr-v1` is an explicitly selected new SDR working pipeline. An old clip remains legacy until a deliberate conversion action. Schema version describes data shape; evaluator version describes mathematics, including sampling and rounding. Neither may change implicitly on reopen.

One serial list of typed operations is authoritative within a grade. Creative and Pro are views/editors of that list; they do not store separate grades. Named presets are immutable snapshots of operations, not hidden overrides. Spatial masks and qualifiers are explicit selection resources; they cannot be folded into a global 3D LUT. No parallel-node graph, alternate rendering engine, cloud service or framework is introduced.

### 2. Preserve projects before adding tools

Missing `grade` uses legacy fields directly, without a database write. A future migration action may wrap the complete legacy color payload into an exact legacy adapter; it must not reinterpret exposure, contrast, warmth or tone sliders as scene-linear operations. Legacy keys become frozen rollback evidence once the envelope is authoritative. No dual writes. All old UI/API/action writers must reject canonical clips until their bridge is installed; otherwise they could mutate ignored fields.

Conversion to managed SDR is a separate undoable user action with a preview and explicit warning that appearance can change. It does not claim pixel-identical translation of YUV `eq` to RGB math. Saving/reopening, rescanning, undo/redo and cutting must retain all unrecognized data. Unknown enabled operations or evaluator versions block rendering and grading edits; no silent neutral fallback. Corrupt canonical data produces a recoverable error without overwriting the stored JSON. Old releases do not understand canonical grades: minimum-reader enforcement and a backup/recovery path are prerequisites to first write, not a promise of backward execution in old binaries.

### 3. Make numerical behavior part of the API

Managed SDR uses straight-alpha linear BT.709 RGB between operations, with explicitly tagged encoded-domain operations. Input decoding, confirmed technical conversion, transfer decoding, ordered grade operations, output transfer, output matrix/range and quantization are distinct stages. There is no automatic D-Log M conversion from an SRT hint. No implicit creative LUT, hidden tone map or global per-operation clamp. LUT domain, order, interpolation, blend domain and precision are part of the render plan. Managed and legacy paths cannot be mixed without explicit domain adapters.

Spatial selection evaluates on the input of its own step in source-oriented image coordinates. The step blends its processed result through that selection. Reordering steps can change qualifier results and is therefore an undoable semantic edit. Source geometry is graded before framing and project compositing. Final MP4 transitions/compositing retain their existing contract until a dedicated integration issue proves any proposed change.

### 4. Share an inspectable render plan

A pure evaluator produces a versioned render plan consumed by existing FFmpeg still/proxy/export adapters and the existing WebGL preview adapter. It contains ordered operations, domains, resolved immutable LUT digests, evaluated time, precision and required features. Adapters report exact/approximate/unsupported per plan; they must not silently drop stages or apply a stage twice. Unsupported GPU features use a supported FFmpeg still/proxy route or honest unavailable state. A new engine is not authorized.

Cache identity includes semantic inputs and implementation versions. Browser asynchronous results must match project, clip, grade revision and request generation before display. No new still request per playback frame. Early proxy scaling is an explicitly approximate optimization until validated; it is not mathematically equivalent to grading then scaling.

### 5. Evidence and ownership gate integration

Keep legacy gate L320 (#320) **unchanged**, including decoder/extractor, ROIs, maximum swatch RGB error **<=3.0**, historical FAILs and stopped precision work. The new managed evaluator has a SEPARATE proposed gate M709-SRGB8-v1: decode actual export BT.709 OETF and preview sRGB to common linear BT.709/D65, then encode both to sRGB and quantize identically for comparison. Raw sRGB versus BT.709 code comparison is invalid for managed grades; gray .18 differs by about 13.35 RGB8 levels without normalization. See the contract for exact range/matrix, decoder/scaler, quantization, alpha, tolerance and reference-vector requirements. Managed PASS cannot close #320. Color, detail, temporal correctness, source hashes and performance are separate gates; one cannot compensate for another. Existing failed precision experiments remain rejected. Fixtures must include spatial detail, mixed transitions, native neutral images and LUT boundaries, beyond flat swatches.

Codex owns engine contracts and implementations; Cursor owns workspace/inspector UI; OpenCode owns new isolated evidence. Shared persistence, history, actions, routes, render orchestration and existing tests are serial integration gates with one named owner per PR. Independent review is distinct from implementer self-review. Only the Product Owner may approve the architecture, sequencing and merges.

## Alternatives considered

1. Replace all legacy color JSON in place: rejected because old clips would change appearance and undo snapshots could be lossy.
2. Maintain independent Creative/Pro grades or CSS/FFmpeg formulas: rejected because save/export semantics diverge.
3. Encode every operation as a global LUT: rejected because masks, qualifiers with spatial dependencies and scopes require image context.
4. Replace FFmpeg or add a general NLE/node engine: rejected; unnecessary new architecture and packaging risk.
5. Upgrade all intermediates to float immediately: rejected. #320 demonstrated detail/performance trade-offs; representation changes need their own approved tests and retention gate.

## Consequences

- Positive: one explicit data authority, inspectable domains, complete feature coverage, incremental adapters and rollback-aware migration.
- Costs: legacy and managed evaluators coexist; GPU coverage is incremental; exact compatibility requires retaining old semantics rather than renaming sliders.
- The complete feature package cannot honestly be advertised until the final evidence matrix passes. Approximate preview remains labeled as such.
- Follow-up implementation requires architecture acceptance plus separately approved issues. Proposed names, limits and budgets below are reviewable contracts, not measured performance or shipping APIs.

## Binding PO engineering criteria and review correction

The additional criteria recorded across 47 issues apply: isolated worktrees, modular domain logic, reuse of Studio patterns/adapters/actions/history, approved UI/tokens/A11y/DE/EN, shared validated API-first actions, safe MCP capability/revision/target contracts, and real journey/regression evidence. The contract maps each to owners and downstream issues and records Phase-A nonapplicability: no runtime API, UI, MCP or E2E was implemented. No dummy endpoint or fabricated journey pass is allowed.

This revision addresses [REVIEW_CHANGES_REQUESTED](https://github.com/Magehawks/orga-drone/pull/367#issuecomment-6803782603) and the [inline transfer finding](https://github.com/Magehawks/orga-drone/pull/367#discussion_r4541102237). [Review evidence](../architecture/COLOR_WORKSPACE_REVIEW_EVIDENCE.md) supplies transfer vectors and the exact develop/PR CI comparison. Both original required CI jobs FAILED, not pending: baseline Prettier issues and the isolated LUT lifecycle harness's missing fullscreen helper. No production/test fix is mixed into this architecture PR. Independent re-review remains required.

## Open decisions and approval record

The proposal selects BT.709 SDR as the first managed working profile; HDR/wide-gamut delivery is an extension requiring its own profile contract, not a removal of input/output transforms. Confirm this profile, the bounded operation/resource limits, and the proposed performance budgets at architecture approval. If a required local FFmpeg build cannot implement a stage faithfully, do not substitute different math: record an adapter capability failure and obtain a scoped implementation decision. Before any canonical write the PO must approve concrete minimum-reader/startup enforcement, separate database and backup naming/location/permissions, backup checksum/restore validation, downgrade recovery and explicit loss-of-later-edits consent. #351 cannot resolve these by silently enabling writes. All implementation, including fixture-backed work, first requires ADR acceptance. Tracking remains an explicit dependency of moving masks, not an implicit Phase-A commitment.

No production implementation, migration, parity measurement or architecture approval is provided by this ADR. Independent review and Product Owner decision are pending.
