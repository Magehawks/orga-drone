# Color Workspace contract test matrix (#350 pre-integration evidence)

OpenCode evidence lane (ADR 0035 ownership split). This matrix maps the
approved contract to deterministic tests. The suite was written **against the
contract**, not against Codex's in-flight #350 branch; engine tests are armed
and report NOT_RUN until `orga_drone.studio_grade_model` /
`orga_drone.studio_grade_plan` exist on develop.

- Contract: `docs/decisions/0035-color-workspace-contract.md` +
  `docs/architecture/COLOR_WORKSPACE_CONTRACT.md` (Phase A, merged with PR
  #367; baseline develop 8ff2545).
- Issue: #350 (implementation, Codex owner). This suite: #364-adjacent
  independent evidence, no production edits.
- Reference vectors: `docs/architecture/COLOR_WORKSPACE_REVIEW_EVIDENCE.md`.

## Files

| File | Role |
|---|---|
| `tests/color_workspace_reference.py` | Independent contract-math oracle (stdlib only): transfers S/B/D_s/D_b, Q8, primaries-v1, wheels-v1, curves, encoded-domain HSL ops, tetrahedral LUT sampling with domains, selection masks/qualifier blend. Never imported by production; never monkeypatches it. |
| `tests/test_color_workspace_reference_vectors.py` | Verifies the oracle against the published transfer/alpha vectors and contract-derived operator semantics. |
| `tests/test_grade_contract.py` | Armed contract tests for read/validation/evaluate/commands. Auto-activate when #350 merges; NOT_RUN before that with an explicit reason. |
| `tests/test_grade_legacy_compat.py` | Live legacy-compatibility evidence against EXISTING modules (pure reads, unknown-member behavior, malformed fallback, no canonical writes). |
| Reused, not duplicated | `tests/test_studio_color_scenarios.py` + feature tests from PR #368 own legacy operation semantics/ordering; `test_studio_grade_model.py` (Codex) will own engine-internal unit evidence when merged. |

## Status matrix

Legend: **PASS** runs today, **NOT_RUN** armed pending #350, **N/A Phase A**
per ADR/contract with the owning issue.

| # | Contract area | Test | Status |
|---|---|---|---|
| 1.1 | Missing grade = legacy, no write on read | `test_missing_grade_is_legacy_without_writing` | NOT_RUN |
| 1.2 | grade:null / malformed / null scalar = errors, not reset | `test_null_scalar_and_null_grade_are_errors_not_reset` | NOT_RUN |
| 1.3 | Unknown evaluator read-only, never neutral fallback | `test_unknown_evaluator_is_read_only_never_neutral` | NOT_RUN |
| 1.4 | Legacy readers pure + deterministic (existing modules) | `test_readers_are_pure_and_deterministic` (6 readers) | PASS |
| 1.5 | Reads never introduce a canonical envelope | `test_reads_never_introduce_a_canonical_grade` | PASS |
| 1.6 | Dump functions preserve unrelated top-level members | `test_dump_functions_preserve_unrelated_top_level_members` | PASS |
| 1.7 | Documented gap: nested feature members dropped by legacy dumps | `test_dump_functions_replace_nested_feature_members_documented_gap` | PASS |
| 1.8 | Malformed legacy text → existing defaults, no raise | `test_malformed_legacy_text_falls_back_to_defaults` (5 cases) | PASS |
| 1.9 | section_repeats / forward-loop defaults stable | `test_legacy_section_repeats_reader_survives_unknown_members` | PASS |
| 2.1 | schema_version / evaluator distinction | `test_schema_version_and_evaluator_are_distinct_fields` | NOT_RUN |
| 2.2 | Stable IDs, no dangling selection references | `test_stable_ids_and_no_dangling_references` | NOT_RUN |
| 2.3 | Unknown disabled op preserved byte-for-value + bypassed | `test_disabled_unknown_operation_is_preserved_and_bypassed` | NOT_RUN |
| 2.4 | Unknown enabled op rejects (UNSUPPORTED_GRADE) | `test_unknown_enabled_operation_rejects` | NOT_RUN |
| 2.5 | Structural caps 32/32/4096/100000/4 MiB atomic | `test_structural_limits_reject_atomically` | NOT_RUN |
| 2.6 | Nonfinite numbers rejected | `test_nonfinite_numbers_are_rejected` | NOT_RUN |
| 2.7 | Missing optional params → neutral defaults | `test_missing_optional_params_materialize_neutral_defaults` | NOT_RUN |
| 2.8 | Steps once, array order, empty steps = identity grading | covered by 3.x plan tests + #350 engine evidence | NOT_RUN |
| 3.1 | Deterministic plan + digest | `test_evaluation_is_deterministic` | NOT_RUN |
| 3.2 | Plan carries domains/order/versions/capabilities | `test_plan_carries_domains_order_and_requirements` | NOT_RUN |
| 3.3 | Explicit timing; source_local = pts − source_in | `test_plan_timing_references_are_explicit` | NOT_RUN |
| 3.4 | Pure evaluation: no disk/DOM side effects | `test_pure_evaluation_writes_nothing` | NOT_RUN |
| 3.5 | Digest excludes revision + disabled ops | `test_semantic_digest_excludes_revision_and_disabled` | NOT_RUN |
| 3.6 | Asset requirements explicit; no silent skip | #350 plan tests + #352 gate | NOT_RUN |
| 4.1 | Stale revision conflicts without mutation | `test_stale_revision_conflicts_without_mutation` | NOT_RUN |
| 4.2 | Detached command results; persisted=false | `test_command_result_is_detached` | NOT_RUN |
| 4.3 | Transfer vectors S/B/D_s/D_b + Q8 (published) | 6 vector cases + negative control + quantization + toe branches | PASS |
| 4.4 | Alpha vectors (50%/transparent/readback) | 3 cases | PASS |
| 4.5 | primaries-v1 / wheels-v1 / curves / HSL / LUT / selection semantics vs oracle | 12 semantic cases | PASS |
| 4.6 | Real adapter taps / WebView2 / EXE evidence | Windows + GPU required | N/A Phase A → #364/#365 |
| 4.7 | M709-SRGB8-v1 managed gate | Phase A NOT_RUN by ADR | N/A Phase A |
| 4.8 | Persistence/history write guards (#351) | #351 single-owner gate | N/A → #351 |
| 4.9 | Actions/routes/DOM/MCP binding (#363) | #363 serial gate | N/A → #363 |
| 4.10 | Scope tap (#366) / Scopes UI (#362) | #366 engine, #362 display | N/A Phase A |

## Contract gaps and integration risks (observed, not fixed here)

1. **Nested unknown-member gap (1.7):** today's dump functions replace the
   feature object they own. Legacy storage relying on unknown nested members
   inside `image`/`color`/`hsl`/`color_wheels` loses them on ANY legacy edit.
   The canonical model's recursive preservation closes this; until then the
   gap stays visible and must not be silently "fixed" in legacy dumpers.
2. **API-name risk on activation:** armed tests assert the ADR's proposed
   module/function names (`read_grade`, `validate_patch`,
   `evaluate_grade`, `to_dict`, `semantic_digest`, `original_effect_settings`).
   If #350 ships different names, activation produces FAILs that must be
   reconciled with the ADR (update tests + ADR references), not silenced.
3. **Evaluator semantics vs. plan sampling:** the foundation evaluates plans
   at one sampled time; legacy animation eligibility/approximation rules
   remain with the historical renderer. A plan digest alone cannot certify
   animation playback correctness — segmentation capability must be part of
   any cache identity (#358/#359).
4. **`grade: 12` (scalar) is ignored by legacy readers** (1.8 evidence):
   pre-canonical databases containing a malformed scalar would be read as
   legacy today. The contract makes null scalars an error for the canonical
   reader — the boundary between legacy tolerance and canonical strictness is
   exactly the damaged-JSON INVALID_GRADE rule (#351 must never overwrite a
   failed read).
5. **No production integration exists yet:** there is no route/action that
   reads canonical grades, so no runtime surface can regress today. The
   armed suite plus the legacy locks are the integration tripwire for
   #351/#363.

## Review request

Independent review is requested for: contract fidelity of the oracle
(`color_workspace_reference.py`), the NOT_RUN arm/unarm design, and the
gap/risk list. The reviewer should confirm no production file, schema,
renderer or UI file is touched and that #320's L320 gate/tolerances are
unchanged.
