# Local dehaze closeout (#302)

Status: **discovery complete; NO-GO for a Dehaze product control** in the
current FFmpeg-only Studio pipeline and **NO-GO for adding a Dehaze operator**
to the Color Workspace grade contract without a new architecture approval.

Pinned tree: `origin/develop` at `ed22c9d` (2026-11-24).

## Classification

| Issue | Classification | Evidence | Product action |
|---|---|---|---|
| #302 | **Completed discovery** | [`302-local-dehaze.md`](302-local-dehaze.md), [`302-local-dehaze-validation.md`](302-local-dehaze-validation.md), benchmark + measurements, CI unit tests | Recommend PO close as discovery NO-GO |

## Acceptance matrix

| Criterion | Result |
|---|---|
| Audit of existing contrast/tonal/detail chain | PASS (documented) |
| Synthetic before/after vs clean reference | PASS (global transform helps synthetic) |
| Real aerial fixtures, same-frame comparison | PASS (private fixtures; metrics in JSON) |
| Incremental value vs existing contrast | FAIL on real footage (does not clearly beat contrast; crushes clear/sunset) |
| Halos / oversaturation failure cases | PASS (global transform has no spatial halos; color shift and shadow crush documented) |
| 4K cost estimate | PASS (~0.48 s/s added on host CPU ultrafast encode) |
| Packaged Windows EXE / WebView2 | NOT_RUN (explicit gap; discovery only) |
| Preview/playback/export parity design | NOT_RUN for product; risks documented |
| GO for shipping Dehaze slider | **NO-GO** |
| GO for per-pixel dark-channel in current architecture | **NO-GO** |

## Color Workspace / operator contract

ADR 0035 and `docs/architecture/COLOR_WORKSPACE_CONTRACT.md` define the
approved managed operator inventory (`primaries-v1`, tone, LUT, spatial
selections, etc.). **Dehaze is not an approved operator.** A FFmpeg-only global
veil subtraction must not be smuggled into legacy `image` adjust or managed
primaries without:

1. a new product-approved implementation issue;
2. an ADR amendment naming a versioned operator and evaluation domain;
3. preview/proxy/export parity evidence;
4. proof that clear/sunset/cloud controls do not destroy shadows at usable
   strengths.

Until then, keep Dehaze out of Studio UI, `effect_settings`, MCP actions, and
the managed grade list. Prefer existing exposure/contrast/highlights/shadows/
blacks for haze-like grading.

## Quality / performance highlights (from validation)

- Synthetic: global 50–100% improved PSNR/SSIM vs hazy input.
- Real haze scenes B/C/F: clearer distance layers at high strength.
- Real clear/sunset D/E: near-black share jumps to ~17–40% at full strength.
- Naive white atmosphere on cloudy skies can crush >50% of samples.
- Dehaze `colorlevels` median cost ~0.28 s/s (1080p) and ~1.08 s/s (4K) in the
  committed timing table (CPU, ultrafast).

## Close recommendation

Recommend the Product Owner **close #302 as completed discovery (NO-GO)**. Do
not open a Dehaze UI issue until a feasible local approach clears architecture
and product gates. Agents must not close the issue without PO authorization.

## Regression contract

`tests/test_dehaze_benchmark.py` keeps discovery maths in required CI
(`pytest` job). It asserts neutral identity, atmosphere caps, synthetic
improvement, and FFmpeg `colorlevels` agreement. It does **not** claim a
shipping Dehaze feature.

## Shadow-protect probe (2026-11-24)

A discovery-only luma-gated blend (`apply_levels_shadow_protect`) reduces near-black crush versus raw global subtraction on a dark synthetic control, but still darkens relative to the source and provides no haze-vs-clear scene gate. It does **not** reopen a Dehaze operator under ADR 0035. See [`298-302-blocker-reconfirm.md`](298-302-blocker-reconfirm.md).
