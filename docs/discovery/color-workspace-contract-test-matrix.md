# Color Workspace contract test matrix (#350 integration re-review)

OpenCode evidence lane (ADR 0035 ownership split). This matrix maps the
approved contract to deterministic tests. **Integration state: PR #370
merged the #350 foundation** (develop 51d9de3); the previously armed engine
tests are activated and run for real. This revision documents the
re-review: deviations between my original assumptions, the ADR and the
implemented foundation, and which areas stay behind later gates.

- Contract: `docs/decisions/0035-color-workspace-contract.md` +
  `docs/architecture/COLOR_WORKSPACE_CONTRACT.md` (Phase A, PR #367).
- Foundation: PR #370 / #350 (Codex owner) — `studio_grade_model.py`,
  `studio_grade_plan.py`, `studio_grade_commands.py`,
  `studio_grade_contract.py`.
- Reference vectors: `docs/architecture/COLOR_WORKSPACE_REVIEW_EVIDENCE.md`.

## Files

| File | Role |
|---|---|
| `tests/color_workspace_reference.py` | Independent contract-math oracle (stdlib only), never imported by production. |
| `tests/test_color_workspace_reference_vectors.py` | Oracle vs. published transfer/alpha vectors + operator semantics (23 tests). |
| `tests/test_grade_contract.py` | **Active** contract tests against the merged foundation (23 tests): legacy authority, envelope validation, render plan, commands. Guards remain: if the foundation modules disappear from develop, tests return to NOT_RUN with an explicit reason. |
| `tests/test_grade_legacy_compat.py` | Live legacy-compatibility evidence (15 tests). |
| Reused, not duplicated | PR #368 scenario tests (legacy op semantics), Codex's `tests/test_studio_grade_model.py` (engine-internal units). |

## Re-review outcome: assumption corrections vs. contract deviations

The first activation run had 10 failures. Classification:

### A. Wrong assumptions in my tests (fixed, assertions NOT weakened)

1. **`validate_patch` module**: ships in `studio_grade_commands.py`, not
   `studio_grade_model.py`. The ADR lists it among engine interfaces without
   pinning the module; the foundation doc documents the commands module. It
   is a **#350 function** — NOT deferred to #351/#363, which only wire it
   into routes/actions/MCP with authorization/revision allocation. The
   reviewer question is answered: no contract violation; my import path was
   wrong.
2. **`RenderContext` shape**: frozen dataclass with `Fraction` rational
   fields, not a JSON dict. Contract requires "rational source PTS/frame
   index" — the dataclass satisfies it; tests construct it directly.
3. **Step members `mix` and `selection_id` are REQUIRED** (explicit null
   allowed). The contract lists them as shape members without an
   optional-marker and separately says missing optional step *parameters*
   materialize defaults — the stricter reading is contract-conformant and
   accepted. Note: this initially made my caps test "pass" for the wrong
   reason (mix error before cap check); cap tests now assert the exact
   `GradeError.path`.
4. **Registered operations**: only `legacy-stack-v1` exists. My placeholder
   "registered-op-v1" was fiction; active-step tests now use the legacy
   wrapper shape (legacy-v1 + legacy-native domains) or disabled-only
   managed plans.
5. **Command params**: `reorder_steps` uses `params.ids` (not
   `ordered_ids`); animation entries require their own `id`.

### B. Documented foundation deviations/observations (no test weakening)

1. **Error-path prefix inconsistency (cosmetic)**: JSON-tree failures
   (nonfinite, nesting) report `$.grade.steps[0].mix`-style paths while
   schema-level failures report `grade.steps[0].mix`. Both are stable per
   error class; asserted exactly as observed and flagged for #352/#363
   transport mapping (error paths surface in API/MCP responses).
2. **Ambiguous damaged text becomes legacy + diagnostics** (no raise);
   damaged text with a recognizable root `grade` member raises
   INVALID_GRADE. The contract's "malformed grade is an error" applies to
   recognizable grade data; the foundation's split is documented in its own
   doc and test-locked in
   `test_corrupt_canonical_json_splits_recognizable_from_ambiguous`.
3. **Animation entries: unconditional UNSUPPORTED_GRADE** after
   reference/clock validation — #358 accepts advertised scalar targets;
   unsupported targets still reject (`test_unsupported_animation_targets_still_reject`,
   `tests/test_studio_grade_animation.py`).
4. **Non-null technical LUT metadata: UNSUPPORTED_GRADE at read** —
   deliberate #352 gate, tested as rejection
   (`test_technical_lut_metadata_rejects_until_352`).
5. **Managed plans claim no execution**: `capabilities.ffmpeg/gpu =
   "not-integrated"`, `pixel_execution = false` — matches "no runtime
   surface yet"; adapters arrive with #359/#360.

### C. Real contract violations found

None. All 10 initial failures resolve to (A) wrong test assumptions or (B)
documented, deliberate gate semantics. #320 tolerances untouched.

## Status matrix (current)

Legend: **PASS** = runs and passes against merged develop 51d9de3;
**GATE** = behind a later issue with owner; **N/A Phase A** per ADR.

| # | Contract area | Test | Status |
|---|---|---|---|
| 1.1 | Missing grade = legacy, no write on read | `test_missing_grade_is_legacy_without_writing` | PASS |
| 1.2 | grade:null / null scalar = errors, not reset | `test_null_scalar_and_null_grade_are_errors_not_reset` | PASS |
| 1.3 | Unknown evaluator typed UNSUPPORTED_GRADE | `test_unknown_evaluator_is_read_only_never_neutral` | PASS |
| 1.4 | Corrupt JSON: recognizable root → error; ambiguous → legacy+diagnostics | `test_corrupt_canonical_json_splits_recognizable_from_ambiguous` | PASS |
| 1.5 | Legacy readers pure + deterministic (existing modules) | `test_readers_are_pure_and_deterministic` | PASS |
| 1.6 | Reads never introduce a canonical envelope | `test_reads_never_introduce_a_canonical_grade` | PASS |
| 1.7 | Dump functions preserve unrelated top-level members | `test_dump_functions_preserve_unrelated_top_level_members` | PASS |
| 1.8 | Documented gap: nested feature members dropped by legacy dumps | `test_dump_functions_replace_nested_feature_members_documented_gap` | PASS |
| 1.9 | Malformed legacy text → existing defaults | `test_malformed_legacy_text_falls_back_to_defaults` | PASS |
| 2.1 | schema_version / evaluator distinction | `test_schema_version_and_evaluator_are_distinct_fields` | PASS |
| 2.2 | Duplicate IDs / dangling references reject | `test_duplicate_ids_and_dangling_references_reject` | PASS |
| 2.3 | Disabled unknown op preserved + bypassed | `test_disabled_unknown_operation_is_preserved_and_bypassed` | PASS |
| 2.4 | Enabled unknown op rejects (UNSUPPORTED_GRADE at type path) | `test_unknown_enabled_operation_rejects` | PASS |
| 2.5 | Caps 32 steps / 32 selections / 4 MiB, exact paths | `test_structural_limits_reject_atomically` | PASS |
| 2.6 | Nonfinite rejected, `$.`-tree path | `test_nonfinite_numbers_are_rejected` | PASS |
| 2.7 | Legacy wrapper exact shape enforced | `test_legacy_wrapper_requires_its_exact_shape` | PASS |
| 3.1 | Deterministic plan + digest | `test_evaluation_is_deterministic` | PASS |
| 3.2 | Plan carries evaluator/schema/domains/capabilities | `test_plan_carries_domains_order_and_requirements` | PASS |
| 3.3 | Timing invariant source_local = pts − source_in | `test_plan_timing_invariant_is_enforced` | PASS |
| 3.4 | Pure evaluation: no disk/DOM side effects | `test_pure_evaluation_writes_nothing` | PASS |
| 3.5 | Digest excludes revision + disabled ops | `test_semantic_digest_excludes_revision_and_disabled` | PASS |
| 3.6 | Legacy plan: established op order, domains, defaults, filtering | `test_legacy_evaluation_keeps_established_order_and_domains` | PASS |
| 4.1 | Stale revision → STALE_REVISION, no mutation | `test_stale_revision_conflicts_without_mutation` | PASS |
| 4.2 | Detached proposals, persisted=false, exact permutation | `test_command_result_is_detached_and_unpersisted` | PASS |
| 4.3 | Unknown/extra command fields reject; legacy never wrapped | `test_unknown_command_rejects_without_mutation` | PASS |
| 4.4 | Animation gate (#358) | `test_unsupported_animation_targets_still_reject`, `test_supported_primaries_animation_is_accepted`, `tests/test_studio_grade_animation.py` | PASS |
| 4.5 | Technical LUT gate (#352) | `test_technical_lut_metadata_rejects_until_352` | PASS (as rejection) |
| 4.6 | UNSUPPORTED_INPUT_PROFILE (HDR/log) | `test_unsupported_managed_input_profile_is_typed` | PASS |
| 4.7 | Transfer/alpha vectors + operator semantics vs oracle | 23 vector/semantic tests | PASS |
| 5.1 | Managed ACTIVE operator evaluation (primaries-v1 …) | — | GATE → #352 |
| 5.2 | Animation clock evaluation | `tests/test_studio_grade_animation.py` | PASS (plan/clock unit); packaged preview/export NOT_RUN |
| 5.3 | Render adapters consume plans (still/proxy/export) | — | GATE → #359/#360 |
| 5.4 | Persistence/history/revision publication | — | GATE → #351 |
| 5.5 | Routes/actions/DOM/MCP binding, error transport | — | GATE → #363 |
| 5.6 | Scope tap (#366) / Scopes UI (#362) | — | GATE → #366/#362 |
| 5.7 | WebView2/EXE pixel evidence, M709-SRGB8-v1 | — | N/A Phase A → #364/#365 |

## Remaining integration risks

1. **Path-prefix inconsistency** (B1) must be normalized or documented in
   the error-transport mapping (#363) — today's two styles both surface.
2. **Strict step shape**: legacy tools generating steps without explicit
   `mix`/`selection_id` will fail validation; the future command/UI layer
   (#363) must always emit them.
3. **`authority` value spelling**: `GradeModel("legacy", …)` vs. canonical
   "canonical" — asymmetry noted; comparison tests use `!= "canonical"` and
   evaluator equality instead of exact authority strings.
4. **`set_step_mix` on a disabled step** mutates params that stay bypassed —
   proposal semantics only; persistence/history guards (#351) own
   publication, so no risk materializes today.

## Review request

Independent re-review requested for: the assumption-fix classification (A),
the deviation documentation (B), and the "no real violation" verdict. The
reviewer should verify against ADR 0035 §Engine interfaces and
GRADE_MODEL_FOUNDATION.md that validate_patch is correctly attributed to
#350, and that no assertion was weakened relative to the armed version.
