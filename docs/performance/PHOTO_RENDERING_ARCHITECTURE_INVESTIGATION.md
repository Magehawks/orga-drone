# Photo rendering architecture investigation

Tracking: [#551](https://github.com/Magehawks/orga-drone/issues/551)  
Baseline tree: `develop` @ `0034e9257b56a56ba0730364353c36393ad75a5c`  
Evidence: [`evidence/photo-render-investigation/`](evidence/photo-render-investigation/)  
Harnesses: `scripts/perf_photo_render_investigation.py`, `scripts/perf_neon_174_repro.py`

Related: #534 (spatial grading performance), #535 (masking UX), #548–#550 (geometry / object select).

---

## A. Executive summary

Neon Relic full-resolution JPG export (~174 s wall in acceptance) is **expected behavior of the current pure-Python managed-grade path** on a pathological but product-realistic workload: a **59-vertex feathered polygon** plus **multiple spatial grade steps** at **~2.23 MP**, not a mysterious packaging bug and not primarily multiprocessing overhead.

Measured bake on the same machine:

| Workload | Workers | Median bake |
|---|---|---|
| Neon-like 59-vert / 3-step (inline) | 1 | **~126 s** |
| Same | 8 | **~98 s** |
| Simpler stored grade (25-vert / 2-step) | 1 | **~30 s** |
| Same simpler grade | auto/8 | **~19.5 s** |

Acceptance **174 s** includes session/export orchestration on top of bake (~126 s). Gap (~48 s) is consistent with decode/encode, UI/API, progress, and cold process work around the kernel.

**Dominant cost:** interpreted per-pixel Python — especially **polygon edge-distance feather** (`distance_to_segment` / `polygon_coverage`) and **row/pixel grade apply** (`_apply_managed_grade_rows` / `apply_managed_step`). cProfile on a related apply: ~86 s with ~244 M function calls; mask rasterization alone ~27 s cumulative; grade row apply ~60 s cumulative.

**Recommendation:** Keep Python orchestration. **Do not migrate the production renderer to Rust/C#/C++/GPU now.** First ship **vectorized mask rasterization + fused NumPy/OpenCV apply** (optionally a thin native extension later if targets are still missed). Kernel microbenchmarks show C# ~538 MP/s vs pure-Python desat ~6 MP/s, but end-to-end gain will be limited until feather rasterization and pass fusion are fixed — NumPy fill+blur placeholder already shows **~2000×** on the feather hotspot (parity TBD).

**GO / NO-GO for language migration now: NO-GO.**

---

## B. Reproduction evidence

### Machine

| Item | Value |
|---|---|
| OS | Windows 11 Pro `10.0.26300` |
| CPU | AMD Ryzen 7 5700X (8C/16T) |
| RAM | 32 GB |
| GPU | AMD Radeon RX 6700 XT |
| Python | 3.12.3 |
| Execution | Source tree (`PYTHONPATH=src`), not packaged EXE |
| Git SHA | `0034e9257b56a56ba0730364353c36393ad75a5c` |

### Acceptance case (authoritative)

Source run: `acceptance-evidence/masking-ux-e2e/runs/neon-20261121-111511/`

| Metric | Value |
|---|---|
| Image | ~1125×1984 (~2.23 MP) |
| Object proposal | **3.948 s**, 59 points, coverage ~0.335 |
| Still export | **174.41 s** |
| Magenta IoU vs TARGET | **0.57** |

### Why earlier ~8–30 s numbers are not the same workload

| Case | Vertices | Steps (approx) | Workers | Median |
|---|---|---|---|---|
| Brush / simpler spatial (prior notes) | low | fewer | varies | ~8–16 s export class |
| SQLite-extracted neon grade in harness | **25** | **2** | 1 / 8 | ~30 s / ~19.5 s |
| Neon object-select proposal geometry | **59** | **3** | 1 / 8 | **~126 s / ~98 s** |

**Conclusion:** The jump from ~19–30 s to ~100–174 s is **workload scaling** (vertex×pixel feather + more steps), not an unexplained regression of the bake kernel between commits at `0034e92`.

### Neon-like bake timings (`neon174-repro.json`)

| Config | Runs (s) | Median |
|---|---|---|
| workers=1, bake_inline=false | 125.09, 127.69 | **126.39** |
| workers=1, bake_inline=true | 125.93, 127.48 | **126.70** |
| workers=8, bake_inline=true | 97.98, 89.93, 98.45 | **97.98** |

Startup was excluded from bake timers (harness imports after process start). Output PNGs written under evidence for visual spot-check.

### Stage breakdown (simpler 25-vert / 2-step path)

From `investigation-report.json`:

| Stage | Seconds |
|---|---|
| Decode/load | 0.19 |
| Float pack | 0.41 |
| Mask raster (all selections) | **8.73** |
| `apply_managed_grade_image` | **26.14** |
| JPEG encode | 2.02 |
| Staged total | **37.49** |

On the 59-vert path, mask raster alone extrapolates to **tens of seconds to ~96 s** (see NumPy spike estimate).

---

## C. Root-cause analysis

### Top wall-time consumers (cProfile, workers=1 apply, ~86.5 s)

Source: `evidence/photo-render-investigation/cprofile-apply-workers1.txt`

| Rank | Symbol | cumtime (s) | Role |
|---|---|---|---|
| 1 | `apply_managed_grade_image` | 86.5 | Orchestration |
| 2 | `_apply_managed_grade_rows` | 59.5 | Per-pixel grade |
| 3 | `apply_managed_step` | 30.2 | Step evaluation |
| 4 | `rasterize_mask_coverage` / `leaf_coverage` | ~26.8 | Mask weights |
| 5 | `polygon_coverage` / `distance_to_polygon_edges` | ~17.6 / 16.0 | Feather geometry |

### Top CPU / call-volume consumers

| Symbol | ncalls | Notes |
|---|---|---|
| `_distance_to_segment` | ~9.1 M | Per pixel × edges |
| `_encode_profile` / `_decode_profile` | ~4.4 M each | Color lattice churn |
| `apply_managed_step` | ~2.3 M | Near per-pixel×steps |
| `builtins.min` / `max` | ~37 M / ~29 M | Distance / clamps |
| `managed_hsl` | ~2.2 M | Spatial color |

### Full-image passes and copies

- Mask raster: **full-frame per selection leaf** in pure Python (nested x/y loops calling geometry).
- Grade apply: **another full-frame pass** (optionally strip-parallel workers) reading coverage maps.
- Preview path uses ≤512 px short side → same algorithms, far fewer pixels → responsive preview vs slow export (**H7**).
- Multiprocessing (`ORGA_SPATIAL_APPLY_WORKERS`): helps **grade apply strips** (~126→98 s) but **does not parallelize mask raster** in the measured path; EXE historically forces workers=1 to avoid nested pools — correct for packaging, not the root of 174 s.

### Hypothesis results

| ID | Verdict | Evidence | Language change needed? |
|---|---|---|---|
| H1 Python pixel loops | **Confirmed primary** | 244 M calls; polygon distance + row apply | No — vectorize first |
| H2 Repeated mask raster | Partially | Rebuild per export; cache by revision/geometry would help warm paths | No |
| H3 Excessive passes | Confirmed | Separate raster + apply + profile encode/decode | No — fuse later |
| H4 Process orchestration | Secondary | workers 1→8 saves ~28 s of ~126 s; not 174→5 | No |
| H5 Memory copies | Secondary | PIL/list/`array` churn; encode ~2 s | No |
| H6 Mask complexity | Confirmed nonlinear | 25→59 verts: ~30 s→~126 s bake | No — algorithm |
| H7 Preview/export divergence | Confirmed | Resolution-scaled same Python code | No |
| H8 App orchestration | Explains ~174−126 | API/session/export wrapper | Low priority |
| H9 Object proposal ~4 s | Separate | Flood-fill + contour on full res | Optimize separately |
| H10 Architectural coupling | Moderate | Managed grade tied to Python lists; stable buffer API would help backends | Interface only |

---

## D. Benchmark results

### Desaturation kernel (same 2.23 MP buffer, half-mask)

| Implementation | Median | MP/s |
|---|---|---|
| Pure Python | ~0.37 s | ~6.1 |
| NumPy `where` | ~0.068 s | ~33 |
| C# .NET 8 (`DesatKernel`) | ~0.0041 s | **~538** |
| Rust | *not measured* (`rustc`/`cargo` absent on PATH) | — |

Larger NumPy desat samples (8–24 MP class): ~28–32 MP/s sustained.

### Polygon feather probe (59 verts, 282×496 ≈ preview scale)

| Path | Median | Est. full-res |
|---|---|---|
| Pure Python `polygon_coverage` | 6.02 s | **~96 s** |
| NumPy fill+Gaussian blur **placeholder** | 0.0028 s | **~0.045 s** |
| Approx speedup | | **~2100×** |

**Caveat:** placeholder is **not** numerical parity with smoothstep edge-distance feather. It proves the algorithmic class is the bottleneck and that native array ops can remove it; a parity-preserving OpenCV distance-transform or similar is the production candidate.

### Worker sensitivity (simpler grade)

Median materialize: workers=1 **30.1 s**; auto **19.5 s**; 8 **19.4 s**.

### Object proposal

Acceptance: **3.95 s** for classical LAB flood + contour → 59-pt polygon. Separate from export; target &lt;1 s needs downscaled proposal + optional refine, not a renderer rewrite.

---

## E. Technology comparison

| Candidate | Kernel speed (desat) | E2E relevance | Packaging / OSS | Verdict |
|---|---|---|---|---|
| **A Existing Python** | Baseline | 98–174 s Neon-class | Already shipping | Insufficient |
| **B Optimized Python (NumPy/OpenCV)** | ~5× desat; **≫100× feather class** | Likely reaches &lt;5–10 s Neon-class if feather+apply fused | Deps already in ecosystem / optional | **Preferred first** |
| **C Rust** | Expected similar to C# class | FFI + buffer ownership; strong long-term kernel | Extra toolchain, wheels, CI | Deferred hybrid option |
| **D C# / .NET** | **538 MP/s** measured | Poor fit for Python-centric OSS desktop without hosting CLR | Runtime redistribute; Windows-strong, cross-OS cost | **Not preferred** vs Rust/NumPy |
| **E C++** | Likely competitive | Same FFI story; weaker memory safety | Build complexity | Only if library already required |
| **F GPU (WebGL/WebGPU)** | Potentially high | Upload/readback + determinism + CPU fallback; preview path already has WebGL LUT experiments | GPU variance; export parity hard | **No for export now** |

Fairness notes:

- Kernel-only ≠ end-to-end. C# wins microbench; without feather rewrite, E2E stays mask-bound.
- GPU export would need CPU fallback and parity tests; transfer can erase gains at 2 MP.
- Authoritative color reference remains the managed Python lattice until an ADR changes it; any native path needs max/mean error gates.

---

## F. Correctness evidence

- Graded PNG outputs from workers=1/auto/8 harness runs are bit-comparable in workflow (same grade JSON); used for smoke visual check, not IoU.
- Neon acceptance export vs TARGET: IoU **0.57** is a **selection/coverage quality** issue (#550), not a performance metric.
- NumPy feather placeholder: **explicitly non-parity**; production work must match smoothstep signed-distance semantics (or document an approved visual change).
- Recommended gate for any kernel swap: max abs error, mean abs error on synthetic gradients + Neon fixture; preview/export parity at full res.

---

## G. Architecture decision

**Decision:** Hybrid **later**, optimized **Python-first** **now**.

1. Keep FastAPI / Studio / SQLite / managed grade **schema** and orchestration in Python.
2. Introduce a **stable rendering buffer interface** (planar float RGB + coverage maps + grade plan) so apply/raster can move behind a backend without rewriting Studio.
3. Implement **Backend V1**: NumPy/OpenCV mask raster + vectorized spatial apply (CPU).
4. Keep pure-Python path as **correctness oracle** and fallback.
5. Reassess a **small Rust cdylib** only if V1 misses &lt;5 s Neon-class on mid-range Windows after fusion/caching.
6. Do **not** adopt C# as the rendering kernel for this codebase.
7. Do **not** make GPU mandatory for photo export; optional preview acceleration may continue separately.

Video: Studio MP4 export remains ffmpeg filter-graph oriented (`export/`, `studio_export.py`). Photo managed-grade is a **different** pipeline. Shared opportunities: LUT eval, global color ops, mask weight generation for still overlays — via the same buffer interface, **not** a rewrite of the video encoder in this milestone.

---

## H. Migration assessment

| Item | Assessment |
|---|---|
| Expected benefit (V1) | Order-of-magnitude on feather; Neon-class toward **&lt;5–15 s**, stretch **&lt;2–5 s** after apply fusion |
| Implementation cost | Medium: OpenCV distance/feather parity + NumPy apply + tests |
| Risks | Subtle feather/qualifier parity; Windows wheel pins; memory peaks |
| Rollback | Feature flag / env to force pure-Python oracle |
| Maintenance | Prefer fewer native languages; NumPy/OpenCV already common in imaging OSS |
| CI | Add resolution-scaled perf smoke + parity tests; full Neon timing optional/manual |

---

## I. Proposed implementation roadmap

| Priority | Milestone | Acceptance |
|---|---|---|
| P0 | **Parity-preserving polygon/brush feather via OpenCV/NumPy** | Neon-like 59-vert raster &lt;0.5 s @ 2.23 MP; max error vs Python oracle documented |
| P0 | **Coverage map cache** keyed by selection revision + size | Warm re-export skips raster |
| P1 | **Vectorized `_apply_managed_grade_rows`** (fuse profile encode/decode) | Neon-like bake median **&lt;5 s** workers=1 on Ryzen-class; no color ADR change |
| P1 | Progress + cancel already present — verify under new path | UI never hard-freezes |
| P2 | Object proposal downscale + refine | Proposal **&lt;1 s** typical 2 MP |
| P3 | Stable `RenderBackend` protocol + oracle tests | Enables Rust spike without Studio rewrite |
| P4 | Rust feather/apply cdylib **only if** P1 misses targets | E2E advantage ≥2× over NumPy V1 after FFI |
| — | GPU export | Out of scope until CPU path saturates |

Measurable product targets (from charter): warm preview &lt;500 ms; complex 2.23 MP export &lt;5 s (stretch &lt;2 s). If stretch fails after P1, document revised targets with evidence before P4.

---

## J. Explicit non-goals

- No production rewrite of the renderer in Rust/C#/C++/GPU in this investigation.
- No change to `main`, no EXE publish, no release.
- No schema/`effect_settings` break without ADR.
- No video encoder rewrite.
- No labeling of classical flood-fill or grade math as “AI”.
- No dependency added to the production package solely for experiments (kernels remain under `docs/performance/evidence/...`).

---

## K. GitHub tracking

| Item | Status |
|---|---|
| Parent issue | [#551](https://github.com/Magehawks/orga-drone/issues/551) |
| Investigation PR | [#555](https://github.com/Magehawks/orga-drone/pull/555) |
| Independent review | [REVIEW_APPROVED](https://github.com/Magehawks/orga-drone/pull/555#issuecomment-7062537188) |
| CI | [success](https://github.com/Magehawks/orga-drone/actions/runs/44903886311) |
| Merge SHA into `develop` | [`a0ae315`](https://github.com/Magehawks/orga-drone/commit/a0ae31515485dcd861d1915cc1bd84de4084ebdb) |

Follow-up implementation issues:

- [#552](https://github.com/Magehawks/orga-drone/issues/552) — NumPy/OpenCV parity feather + coverage cache (P0)
- [#553](https://github.com/Magehawks/orga-drone/issues/553) — Vectorize managed spatial grade apply (P1)
- [#554](https://github.com/Magehawks/orga-drone/issues/554) — Object proposal toward sub-1s (P2)

---

## Answers to charter questions

1. **Why ~174 s?** Pure-Python feathered 59-vert polygon raster + multi-step per-pixel grade at full res, plus export session overhead on top of ~126 s bake.
2. **Regression vs expected?** **Expected** for this architecture on this workload; earlier 8–30 s cases used simpler masks/steps.
3. **Dominant operation?** Polygon edge-distance feather + `_apply_managed_grade_rows`.
4. **Redundant work?** Separate full-frame raster and apply; weak caching; profile encode/decode per sample.
5. **Python execution itself?** **Primary** — hundreds of millions of interpreter calls.
6. **Copies / process overhead?** Secondary (~2 s encode; ~28 s saved by workers on bake, mask still serial).
7. **Can optimized Python meet targets?** **Likely yes** for &lt;5 s; stretch &lt;2 s plausible after fusion — needs implementation proof.
8. **Rust E2E advantage?** Promising kernel-class; **not required** until NumPy/OpenCV ceiling is measured.
9. **C# advantage?** Fast microbench; **poor product fit** vs NumPy/Rust for this stack.
10. **GPU more appropriate?** Not for export now (parity/fallback/transfer).
11. **Language change necessary?** **No** for the immediate fix.
12. **Lowest-risk improvement?** OpenCV/NumPy feather + coverage cache behind a flag with Python oracle.
13. **Best long-term architecture?** Python orchestration + pluggable CPU kernel (NumPy now, optional Rust later); GPU optional for preview only.
14. **Leave unchanged?** Studio UI, SQLite grade schema, ffmpeg video path, local-first security boundaries, pure-Python oracle.
15. **Future video?** Shared buffer ops possible; do not couple to MP4 filter-graph rewrite now.

---

## Final recommendation (required format)

**ROOT CAUSE**  
Interpreted per-pixel Python for feathered polygon mask rasterization and managed spatial grade apply on multi-megapixel frames — amplified by high vertex counts from object select — with export orchestration on top.

**IMMEDIATE FIX**  
Replace pure-Python polygon/brush feather rasterization with a parity-tested NumPy/OpenCV path; cache coverage maps; then vectorize grade apply. Keep Python as oracle/fallback.

**EXPECTED IMPROVEMENT**  
Feather class: from ~tens–90+ s toward **&lt;1 s** (placeholder ~2000×; parity path expected large but lower). End-to-end Neon-class: from ~100–174 s toward **&lt;5 s** after P0+P1 (evidence-based target; stretch &lt;2 s TBD).

**TECHNOLOGY DECISION**  
Keep Python orchestration; optimize with NumPy/OpenCV first; defer optional Rust hybrid; reject C# and GPU export migration for now.

**WHY**  
cProfile and Neon-like repro localize &gt;90% of bake time in Python geometry/apply loops; NumPy already shows order-of-magnitude headroom; C# wins microbench but adds the wrong packaging/maintenance surface; GPU export risks parity without solving CPU fallback.

**MIGRATION COST**  
Medium for P0/P1 inside Python; low rollback via flag. High cost and OSS friction for C#/.NET hosting. Rust cdylib is a bounded later option with wheel/CI cost.

**NEXT IMPLEMENTATION MILESTONE**  
Issue: “perf: NumPy/OpenCV parity feather raster + coverage cache for managed masks” — AC: Neon-like 59-vert @ 2.23 MP raster &lt;0.5 s; oracle max-error gate; workers=1 bake improved ≥5× on fixture; flag to force pure Python.

**GO / NO-GO**  
**NO-GO** on a technology migration now. **GO** on optimized-Python rendering work from the roadmap above.
