# Color Workspace implementation backlog (proposed)

Parent: [#348](https://github.com/Magehawks/orga-drone/issues/348). Architecture: [ADR 0035](../decisions/0035-color-workspace-contract.md) and [contract](COLOR_WORKSPACE_CONTRACT.md). All issues below are real planning issues, not implementation approvals. Architecture acceptance and individual scope approval precede code. No feature is removed from the product target.

## Parallel lanes and merge order

Foundation and independent evidence come first. Pure operator, UI-with-fakes and scope-with-fakes work can then proceed independently on separate branches. Migration and bridge are serial gates; render adapter integration follows the supported operator capabilities. Each operator must declare adapter support before admission. Workspace/scopes can develop against fixtures before the bridge exists, but cannot merge as shipping tools until their engine support and bridge pass. Final admission waits for every listed feature. Dependencies are prerequisites for integration, not permission for overlapping files.

The final admission issue depends on every deliverable. FFmpeg/GPU adapter issues can integrate incrementally, but final coverage must include later operators; their early closure cannot certify unsupported features. Scope UI and engine-tap wiring require separate PR owners. Tracking remains #298-dependent future integration, not a hidden mask implementation.

## Concrete issues

### [#350: Canonical grade model and pure render-plan evaluator](https://github.com/Magehawks/orga-drone/issues/350)

Owner: Codex. Dependencies: architecture acceptance only.

Implement versioned opaque-preserving grade reader, strict command validation, descriptors and pure render-plan evaluation from ADR 0035. Keep legacy readers untouched.

Acceptance:

- Schema/evaluator distinction, defaults, null errors, structural limits and stable IDs match the approved contract.
- Golden tests cover all legacy color fields and unknown nested members; read alone never writes.
- RenderPlan contains explicit domains, clocks, ordered operations and asset requirements; pure evaluation has no DOM or disk writes.
- Unsupported active operations fail; disabled unknown operations roundtrip unchanged.

Out of scope: No persistence migration, routes, renderer, UI or new color controls.

### [#351: Canonical grade persistence, recovery and history integration gate](https://github.com/Magehawks/orga-drone/issues/351)

Owner: Codex (single serial integration owner). Dependencies: #350.

Implement approved first-write guards, transactional persistence, revision handling and explicit legacy wrapping. Before coding, obtain approval of concrete backup/restore naming, checksum verification, separate database/minimum-reader startup strategy and rollback drill.

Acceptance:

- All legacy setter/reset/cut/merge/reuse and action write paths are inventoried and guarded before canonical writes can occur.
- Save/reopen, rescan, undo/redo and failure injection preserve opaque data and unrelated effects; undo revisions cannot accept stale responses.
- Wrapping legacy image/color/HSL/wheels/detail/ramp/animation retains old render semantics; no automatic managed conversion.
- Verified pre-upgrade backup and restore/downgrade drill succeeds; old executable is never pointed at canonical database; no source bytes change.

Out of scope: No silent bulk conversion, destructive migration, long-lived undo stack or automatic adoption of new tools.

### [#352: Managed SDR input/output transforms and technical/creative LUT contract](https://github.com/Magehawks/orga-drone/issues/352)

Owner: Codex. Dependencies: #350.

Implement explicit managed SDR transfer/primaries boundaries and local LUT validation/sampling metadata. Reuse confined LUT assets; preserve legacy behavior.

Acceptance:

- sRGB/BT.709 vectors, tagged/untagged assumptions and unsupported HDR/log errors match contract.
- Technical conversion requires confirmation and runs once; creative blend domain/zero strength are exact.
- 2..65 cubes, nondefault domains, red-fastest ordering and deterministic tetrahedral ties have golden tests; malformed/1D/shaper inputs are rejected explicitly.
- LUT byte replacement invalidates semantics; missing assets fail export rather than disappear; precision/detail retention gates pass before retention.

Out of scope: No HDR delivery, guessed D-Log transform, new engine or restoration of rejected #320 precision patches.

### [#353: Managed primaries and professional tonal control semantics](https://github.com/Magehawks/orga-drone/issues/353)

Owner: Codex. Dependencies: #350.

Implement exposure, balance, contrast/pivot, tonal mapping and saturation operations as versioned reference functions. Publish exact Kelvin/tint and blacks/shadows/highlights/whites-to-curve mappings and golden vectors for approval before implementing those controls.

Acceptance:

- Linear arithmetic, units, limits, order, negative/zero cases and neutral identity follow contract.
- Tone-control mapping is reviewed, monotone and deterministic across CPU and UI descriptors; no independent UI math.
- Synthetic bright/gray/negative/clipped vectors document predictable behavior without recovery claims.
- Legacy exposure/warmth/YUV contrast and saved appearance remain unchanged.

Out of scope: No inspector/UI, DB edits, automatic legacy conversion or highlight-recovery claims.

### [#354: Complete RGB, luma and hue/saturation curve operators](https://github.com/Magehawks/orga-drone/issues/354)

Owner: Codex. Dependencies: #350.

Implement RGB master/channel, luma, Hue-vs-Hue/Saturation/Luma, Luma-vs-Saturation and Saturation-vs-Saturation types with explicit domains.

Acceptance:

- All seven curve families are covered by identity/nonneutral golden vectors and operation-order tests.
- Piecewise interpolation, extrapolation, strict x ordering, periodic hue endpoints and gray gate follow contract.
- Nonfinite, duplicate-x and oversized curves reject atomically; knots survive roundtrip.
- CPU reference error and LUT-baking/fusion approximation are measured independently; no unbounded spatial operation is baked.

Out of scope: No UI curve editor, arbitrary expressions or implicit Bezier/spline semantics.

### [#355: Compose existing HSL/wheels with professional wheel operations](https://github.com/Magehawks/orga-drone/issues/355)

Owner: Codex. Dependencies: #350.

Reuse legacy HSL and tonal wheel math through explicit adapters; add versioned lift/gamma/gain/offset and managed HSL domains without reinterpreting old points.

Acceptance:

- Legacy 33-cube outputs remain reproducible and legacy order is preserved.
- Lift/gamma/gain/offset neutral, negative, gray, extreme and roundtrip vectors follow the reviewed contract.
- HSL, all wheel types and technical/creative LUTs can compose serially without duplicate application.
- Generated LUT cache keys include operation/evaluator identity and precision; all independent reset cases work.

Out of scope: No UI redesign, hidden conversion of legacy wheels, new engine or spatial masking.

### [#356: Non-destructive linear, radial and brush grading masks](https://github.com/Magehawks/orga-drone/issues/356)

Owner: Codex. Dependencies: #350.

Implement independent source-oriented selection resources and deterministic matte rasterization for all three mask types.

Acceptance:

- Linear/radial feather and brush pressure/radius/hardness match approved equations at pixel centers.
- Union/intersection/subtraction/inversion, empty selection and no-selection cases have analytic fixtures.
- Orientation, aspect ratio, frame crop, DPR/resolution and repeated/trimmed video retain mask registration.
- Rasterizer/content digests and immutable resource IDs survive roundtrip; untouched pixels outside declared support remain unchanged before encoding.

Out of scope: No Cursor handles, privacy-mask replacement, automatic segmentation or tracking; #298 is a separate moving-mask dependency.

### [#357: Secondary RGB/HSL/luma qualifiers and sampled color contract](https://github.com/Magehawks/orga-drone/issues/357)

Owner: Codex. Dependencies: #350.

Implement pointwise qualifiers, sample metadata and selection composition independently of workspace controls.

Acceptance:

- Inner/outer smooth intervals, wrapped hue, gray rejection and product combination match vectors.
- Qualifier samples step input exactly once; coverage/mix preserve alpha and do not depend on processed output.
- Eyedropper returns frame/revision/domain/neighborhood data and never mutates grade without an accepted command.
- Combined qualifier and spatial matte fixtures validate boundaries, inversion and unchanged exterior pixels.

Out of scope: No semantic water/sky/object recognition, UI picker or tracking.

### [#358: Serial grade execution and explicit animation clock integration gate](https://github.com/Magehawks/orga-drone/issues/358)

Owner: Codex (single serial integration owner). Dependencies: #350.

Implement ordered operation execution, selection binding and explicit parameter animation; integrate existing timing mappings without changing the playback clock.

Acceptance:

- Add/remove/reorder/bypass/mix execute each stage once; invalid references fail before mutation.
- Legacy color bar and saturation ramp behavior remains unchanged, including existing eligibility restrictions.
- Source-local and Story-local mapping vectors cover trim, speed ramp, repeats, loop joins and both transition sides.
- Supported animated targets advertise exact interpolation/outside policy; unsupported types reject rather than flatten.

Out of scope: No parallel graph, general NLE clock rewrite, freeform keyframe UI or new transition compositor.

### [#359: FFmpeg still/proxy/export render-plan and cache integration gate](https://github.com/Magehawks/orga-drone/issues/359)

Owner: Codex (single serial integration owner). Dependencies: #350, #352, #358.

Connect the shared plan to existing FFmpeg still, playback proxy and export paths with per-operation capabilities and owned-cache publication.

Acceptance:

- Still/proxy/export use the same supported plan semantics and disclose early-scaling/JPEG/encoding approximations.
- Required masks/qualifiers cannot be silently omitted or globally LUT-baked; unsupported export rejects before output publication.
- Semantic cache invalidation includes LUT content, selection rasterizer, domains, clocks, precision and adapter version; stale/cancelled resources are not published.
- Real decoded application MP4 plus still/proxy regression, source hashes and timing evidence pass; #320 failures remain explicitly tracked.

Out of scope: No new renderer, source rewrite, clock/audio redesign, unsupported-stage bypass or #320 tolerance changes.

### [#360: Existing WebGL GPU adapter for canonical grade operations](https://github.com/Magehawks/orga-drone/issues/360)

Owner: Codex. Dependencies: #350, #352, #358.

Extend the existing WebGL2 adapter using the same approved plan/descriptors; report supported operation coverage explicitly.

Acceptance:

- Tetrahedral off-grid/domain tests and declared intermediate precision meet float reference gates where marked exact.
- Primaries/curves/HSL/wheels/serial selection requirements receive a measured supported path or explicit FFmpeg fallback.
- Already graded proxies are never graded twice; context loss, unsupported texture formats and stale async resources have honest fallback.
- Windows GPU capture validates color, detail and proposed 1080p30 budgets; fixed playback intervals add zero still fetches.

Out of scope: No second rendering engine, blanket float precision patch or unmeasured real-time/quality claims.

### [#361: Complete Creative/Pro Color Workspace and serial grade editing](https://github.com/Magehawks/orga-drone/issues/361)

Owner: Cursor. Dependencies: #350.

Build the complete workspace against fake approved descriptors/command adapters first; integrate through the separate bridge gate. Creative and Pro edit the same grade.

Acceptance:

- Expose primaries, all curve types, HSL, tonal/pro wheels, technical/creative LUTs, input/output transforms, linear/radial/brush masks, qualifier/eyedropper and serial step controls.
- Creative presets compile to inspectable same-grade operations; Pro can inspect/edit without loss; switching mode never mutates pixels or creates shadow grade state.
- Keyboard, focus, DE/EN labels, explicit unsupported/preparing status, reset, stale-target handling and gesture undo are covered.
- Save/reopen and rapid clip/project switches retain grade and selection; UI uses descriptors rather than independent color formulas.

Out of scope: No new engine/DB schema, arbitrary filter expressions, tracking or multi-panel framework; production bridge merge waits for its dependencies.

### [#362: Histogram, waveform, RGB parade and vectorscope from declared render tap](https://github.com/Magehawks/orga-drone/issues/362)

Owner: Cursor (UI only); engine tap belongs to #366. Dependencies: #350; integration waits for #366 and #359.

Implement all four scopes against a documented immutable pixel-frame/tap interface, initially fake fixtures; integrate engine tap only in a named single-owner follow-up PR.

Acceptance:

- Histogram uses 256 bins; waveform/parade use normalized code-value axes with explicit channel/luma labels; vectorscope axes/range/color encoding are documented and tested.
- Tap carries profile, transfer, pre/post grade/composite position, frame/revision, sample rate and ROI; stale frames cannot be shown as current.
- Synthetic black/gray/RGB/color-bar fixtures produce independently expected bins/coordinates; downsampling is visibly disclosed.
- Scope toggles never alter saved grade/export; scope cost and dropped-frame behavior are measured on Windows.

Out of scope: No implied reference-monitor calibration, audio scope, HDR scopes or new rendering engine; exact vectorscope transform must be approved in engine-tap contract before wiring.

### [#363: Canonical grade shared actions, routes, history and workspace bridge gate](https://github.com/Magehawks/orga-drone/issues/363)

Owner: Codex (single serial integration owner; Cursor consumes contract). Dependencies: #350, #351.

Wire approved command/snapshot semantics into existing shared actions, routes, Control API/MCP and workspace DOM bridge; serial ownership only.

Acceptance:

- Every command checks project/clip/revision, validates atomically and preserves unrelated/unknown data; undo groups gestures.
- Image/video capabilities report actual supported operations; coordinate with #296 without expanding it to new tools.
- Async preview tokens bind project/clip/revision/context/generation and prevent stale display after reset/undo/switch.
- Existing legacy API/DOM contracts and Host/Origin/media confinement remain intact; unavailable operations are rejected precisely.

Out of scope: No independent MCP grading semantics, UI layout, schema churn or parallel changes to shared gate files.

### [#364: Independent synthetic Color Workspace parity and performance harness](https://github.com/Magehawks/orga-drone/issues/364)

Owner: OpenCode. Dependencies: #350.

Build isolated synthetic fixture generators and an independent CPU/operator plus real-application evidence harness. Keep existing tests and production files untouched in the parallel lane.

Acceptance:

- Manifest pins source/LUT hashes, grade/plan, build, FFmpeg, WebView2/GPU, frame mapping, ROIs and metric versions.
- All contract fixture families, four render states, mixed transitions, detail/DPR, masks, alpha, cache and source-integrity cases have runnable cases or explicit NOT_RUN.
- #320 maximum swatch RGB <=3.0 is reused unchanged; detail, temporal and performance gates are reported separately; rejected experiments remain FAIL.
- At least five measured cold/warm performance samples report p50/p95 and memory; incomplete matrices cannot become PASS.

Out of scope: No production engine/UI changes, private footage, threshold adjustment, golden images generated solely by the candidate or claim of parity before measured integration.

### [#365: Complete Color Workspace integration and strict acceptance matrix](https://github.com/Magehawks/orga-drone/issues/365)

Owner: Codex (single serial integration owner). Dependencies: #351, #352, #353, #354, #355, #356, #357, #358, #359, #360, #361, #362, #363, #364, #366.

Integrate independently reviewed feature PRs and run the complete Windows/FFmpeg matrix before declaring the full workspace available. No product feature is removed to make admission pass.

Acceptance:

- Every Phase-A target maps to implemented controls/operators/tests; all feature AC and unresolved transform/mapping/tap contracts have PO decisions.
- Undo/redo, save/reopen, rescan, legacy compatibility, source integrity, masks/qualifiers and full serial operation coverage pass.
- Strict <=3.0 RGB, detail-retention, temporal and approved performance gates pass on pinned current candidate; #320 blocked/FAIL cases remain blocking evidence unless PO explicitly decides otherwise without relabeling failures.
- Independent ChatGPT GitHub review and CI evidence are linked; complete/partial/NOT_RUN coverage and remaining limitations are explicit before PO acceptance.

Out of scope: No self-merge, release publication, threshold relaxation, source modification or unsupported completion claim.

## Complete target coverage

Primaries and professional tone: primaries. RGB/luma and all five additional hue/saturation curve families: curves. HSL/pro wheels: wheels/HSL. Qualifiers/eyedropper: qualifiers. Linear/radial/brush masks: masks, workspace and FFmpeg/GPU coverage. Technical/creative LUT and transforms: transforms. Creative/Pro presets on one grade: workspace. All four scopes: scopes. Serial steps and animation clocks: serial/time. Shared semantics and persistence: foundation, migration, bridge and adapters. Measurable parity/performance: independent evidence and final admission. No planned tool is represented as shipped.

## Existing issue boundaries and remaining decisions

#176 is historical tonal work, not approval for the new curve set. #296 remains image access to existing actions; coordinate capabilities with the bridge. #294 forward-loop playback and #267 packaged parity must be covered by admission. #320 remains an open strict parity failure and stopped precision-work decision; this package does not reopen its experiments. #211 animation and #331 shared clocks need compatible integration rather than a new clock engine.

Before implementation: PO accepts ADR/profile, resource limits and proposed performance budgets. Before tonal UI: approve exact tone-control and Kelvin/tint mappings with vectors. Before scope wiring: approve the proposed vectorscope transform/axes and pixel-tap contract. Before canonical writes: approve concrete database backup/startup/downgrade plan and verify every legacy write guard. Before retaining changed precision/scaling: satisfy unchanged detail/color gates. These are assigned, bounded follow-up decisions; none authorizes an unreviewed semantic substitution.

## Additional serial scope-tap gate

### [#366: Scope pixel tap and reference accumulation integration gate](https://github.com/Magehawks/orga-drone/issues/366)

Owner: Codex, one named owner per PR; no workspace UI changes. Dependencies: #350, with render wiring after #359. #362 consumes it and #365 requires it.

Acceptance:

- Implement immutable ScopeFrameV1 with profile/transfer, alpha, ROI, dimensions/stride, frame/PTS, revision and context identity.
- Distinguish clip post-grade/pre-frame tap from the explicitly selected project-composite tap.
- Verify histogram, waveform, RGB parade and BT.709 Cb/Cr vectorscope against independent synthetic counts/coordinates, including alpha weights and range conversion exactly once.
- Disclose deterministic subsampling separately from full-resolution reference; measure resource lifetime/cancellation and performance.

Out of scope: UI, HDR scopes, calibration claims, new renderer or color-threshold changes.

## Review revision: mandatory gates before implementation

The binding engineering criteria on all 47 issues apply in addition to this backlog; see the [contract mapping](COLOR_WORKSPACE_CONTRACT.md#binding-po-engineering-criteria-across-the-47-issue-portfolio). ADR acceptance is required before any implementation, including fixture-backed module/UI work. #351 requires explicit PO decisions for minimum-reader/startup, separate database/backup naming and permissions, verified restore/downgrade and later-edit-loss consent before canonical writes.

#352/#359/#360 must emit/capture declared profiles and implement the reviewed common comparison boundary. #364 must separately report unchanged legacy L320 and proposed managed M709-SRGB8-v1, including the .18 negative-control vector, quantization, alpha, frame/raster metadata and unsupported-reference errors; #365 cannot use a managed PASS to close legacy FAILs. No existing issue or numeric #320 tolerance is changed. Runtime E2E is deferred to those implementation/evidence issues; Phase A evidence is documentation/arithmetic/baseline diagnosis only. See [review evidence](COLOR_WORKSPACE_REVIEW_EVIDENCE.md).
