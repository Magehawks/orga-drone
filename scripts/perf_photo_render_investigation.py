#!/usr/bin/env python3
"""Photo rendering architecture investigation harness (#551).

Reproduces Neon Relic spatial export timings, profiles hotspots, and runs
isolated optimized-Python / language-comparison microkernels.

Usage (from repo root with PYTHONPATH=src):
  python scripts/perf_photo_render_investigation.py
"""

from __future__ import annotations

import cProfile
import json
import os
import pstats
import statistics
import sys
import tempfile
import time
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_DEFAULT_BEFORE = Path(
    r"C:\Users\Niwes\Projects\orga-drone-wt\precision-mask-develop"
    r"\acceptance-evidence\neon-relic\00-before-original.jpg"
)
BEFORE = Path(os.environ.get("ORGA_PERF_BEFORE", str(_DEFAULT_BEFORE)))
NEON_RUN = (
    ROOT
    / "acceptance-evidence"
    / "masking-ux-e2e"
    / "runs"
    / "neon-20261121-111511"
)
OUT = ROOT / "docs" / "performance" / "evidence" / "photo-render-investigation"
OUT.mkdir(parents=True, exist_ok=True)


def _extract_grade_from_sqlite() -> dict | None:
    import sqlite3

    db = (
        ROOT
        / "acceptance-evidence"
        / "masking-ux-e2e"
        / "appdata-merged"
        / "orga-drone.sqlite3"
    )
    if not db.is_file():
        return None
    con = sqlite3.connect(db)
    try:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        # Schema uses studio_clips in current trees; tolerate older names.
        table = "studio_clips" if "studio_clips" in tables else (
            "studio_items" if "studio_items" in tables else None
        )
        if table is None:
            return None
        rows = con.execute(
            f"SELECT id, effect_settings FROM {table} WHERE effect_settings IS NOT NULL"
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    for _sid, raw in rows:
        if not raw:
            continue
        text = raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        grade = payload.get("grade") if isinstance(payload, dict) else None
        if isinstance(grade, dict) and grade.get("selections"):
            names = [s.get("name") for s in grade.get("selections") or []]
            ids = [s.get("id") for s in grade.get("selections") or []]
            if "Blatt" in names or "sel-leaf" in ids:
                return {
                    "schema_version": 1,
                    "evaluator": payload.get("evaluator") or "managed-sdr-v1",
                    "revision": int(payload.get("revision") or 1),
                    "grade": grade,
                }
        if isinstance(payload, dict) and payload.get("evaluator") == "managed-sdr-v1":
            g = payload.get("grade") or payload
            if isinstance(g, dict) and (g.get("selections") or g.get("steps")):
                return {
                    "schema_version": 1,
                    "evaluator": "managed-sdr-v1",
                    "revision": int(payload.get("revision") or 1),
                    "grade": g if g.get("steps") else payload.get("grade", g),
                }
    return None


def _neon_like_grade(points: list[list[float]]) -> dict:
    leaf = {
        "id": "sel-leaf",
        "name": "Blatt",
        "invert": False,
        "overlay": {"visible": True},
        "mask": {
            "combine": "union",
            "leaves": [
                {
                    "type": "polygon",
                    "points": points,
                    "feather": 0.015,
                    "closed": True,
                }
            ],
        },
        "qualifier": {"type": "none"},
    }
    bg = {
        "id": "sel-bg",
        "name": "Hintergrund",
        "invert": True,
        "overlay": {"visible": False},
        "mask": leaf["mask"],
        "qualifier": {"type": "none"},
    }
    return {
        "schema_version": 1,
        "evaluator": "managed-sdr-v1",
        "revision": 1,
        "input": {"profile": "bt709-sdr", "technical_lut": None},
        "working": "linear-bt709",
        "steps": [
            {
                "id": "primaries-leaf",
                "type": "primaries-v1",
                "enabled": True,
                "mix": 1.0,
                "selection_id": "sel-leaf",
                "params": {
                    "exposure": -0.15,
                    "kelvin": 6000,
                    "tint": -88,
                    "contrast": 1.26,
                    "pivot": 0.36,
                    "saturation": 1.12,
                    "blacks": -14,
                    "shadows": -2,
                    "highlights": -32,
                    "whites": -20,
                },
            },
            {
                "id": "hsl-leaf",
                "type": "managed-hsl-v1",
                "enabled": True,
                "mix": 0.90,
                "selection_id": "sel-leaf",
                "params": {"hue": -36, "saturation": 1.16, "lightness": -0.08},
            },
            {
                "id": "hsl-bg",
                "type": "managed-hsl-v1",
                "enabled": True,
                "mix": 1.0,
                "selection_id": "sel-bg",
                "params": {"hue": 0, "saturation": 0.0, "lightness": -0.05},
            },
        ],
        "selections": [leaf, bg],
        "animation": [],
        "output": {"profile": "bt709-sdr", "gamut": "clip"},
        "extensions": {},
    }


def _load_or_build_grade() -> tuple[dict, str]:
    extracted = _extract_grade_from_sqlite()
    if extracted and extracted.get("grade"):
        return extracted["grade"], "sqlite-neon-acceptance"
    # Rebuild via object select + Neon recipe (same as acceptance driver).
    from orga_drone.studio_object_select import propose_object_polygon

    seeds = [
        (0.42, 0.70),
        (0.48, 0.72),
        (0.52, 0.68),
        (0.45, 0.78),
    ]
    best = None
    for u, v in seeds:
        try:
            prop = propose_object_polygon(BEFORE, u, v, max_edge=640, tol=16.0)
        except Exception:
            continue
        cov = prop.coverage
        score = cov if 0.12 <= cov <= 0.55 else -abs(cov - 0.30)
        if best is None or score > best[0]:
            best = (score, prop.points, (u, v), cov)
    if best is None:
        raise SystemExit("Could not build Neon-like polygon proposal")
    return _neon_like_grade(best[1]), f"object-select-seed-{best[2]}-cov-{best[3]:.3f}"


def _timed_materialize(grade: dict, workers: str | None, runs: int = 3) -> dict:
    from orga_drone.studio_managed_spatial_export import materialize_spatial_managed_media

    times: list[float] = []
    env_key = "ORGA_SPATIAL_APPLY_WORKERS"
    prev = os.environ.get(env_key)
    try:
        if workers is None:
            os.environ.pop(env_key, None)
        else:
            os.environ[env_key] = str(workers)
        # Also force bake inline so we measure apply, not spawn nesting.
        os.environ["ORGA_SPATIAL_BAKE_INLINE"] = "1"
        for i in range(runs):
            with tempfile.TemporaryDirectory(prefix="perf-neon-") as tmp:
                work = Path(tmp)
                t0 = time.perf_counter()
                dest = materialize_spatial_managed_media(
                    BEFORE,
                    grade,
                    work,
                    kind="photo",
                    grade_digest=f"perf-{workers}-{i}",
                )
                dt = time.perf_counter() - t0
                times.append(dt)
                assert Path(dest).is_file(), dest
                if i == 0:
                    out_copy = OUT / f"graded-workers-{workers or 'auto'}.png"
                    out_copy.write_bytes(Path(dest).read_bytes())
    finally:
        if prev is None:
            os.environ.pop(env_key, None)
        else:
            os.environ[env_key] = prev
        os.environ.pop("ORGA_SPATIAL_BAKE_INLINE", None)
    times_sorted = sorted(times)
    return {
        "workers": workers or "auto",
        "runs": times,
        "min": min(times),
        "max": max(times),
        "median": statistics.median(times),
        "mean": statistics.mean(times),
        "p95": times_sorted[max(0, int(0.95 * (len(times_sorted) - 1)))],
    }


def _profile_apply(grade: dict) -> dict:
    from PIL import Image

    from orga_drone.studio_managed_apply import apply_managed_grade_image

    with Image.open(BEFORE) as im:
        rgb = im.convert("RGB")
        w, h = rgb.size
        rows = [list(rgb.getdata())[y * w : (y + 1) * w] for y in range(h)]
        # Convert to float rows expected by apply
        frows = [
            [(p[0] / 255.0, p[1] / 255.0, p[2] / 255.0) for p in row] for row in rows
        ]

    os.environ["ORGA_SPATIAL_APPLY_WORKERS"] = "1"
    os.environ["ORGA_SPATIAL_BAKE_INLINE"] = "1"
    pr = cProfile.Profile()
    pr.enable()
    t0 = time.perf_counter()
    apply_managed_grade_image(frows, grade, lattice_domain="srgb")
    wall = time.perf_counter() - t0
    pr.disable()
    os.environ.pop("ORGA_SPATIAL_APPLY_WORKERS", None)
    os.environ.pop("ORGA_SPATIAL_BAKE_INLINE", None)

    stream = StringIO()
    stats = pstats.Stats(pr, stream=stream).sort_stats("cumulative")
    stats.print_stats(40)
    text = stream.getvalue()
    (OUT / "cprofile-apply-workers1.txt").write_text(text, encoding="utf-8")
    # Also dump to binary for snakeviz if available
    pr.dump_stats(str(OUT / "cprofile-apply-workers1.pstats"))
    return {"wall_s": wall, "profile_txt": str(OUT / "cprofile-apply-workers1.txt")}


def _stage_breakdown(grade: dict) -> dict:
    """Coarse stage timings with workers=1 (matches Neon E2E env)."""
    from PIL import Image

    from orga_drone.studio_managed_apply import apply_managed_grade_image
    from orga_drone.studio_managed_selection import rasterize_mask_coverage

    os.environ["ORGA_SPATIAL_APPLY_WORKERS"] = "1"
    stages: dict[str, float] = {}

    t0 = time.perf_counter()
    with Image.open(BEFORE) as im:
        rgb = im.convert("RGB")
        w, h = rgb.size
        pixels = list(rgb.getdata())
    stages["decode_load_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    frows = []
    for y in range(h):
        row = pixels[y * w : (y + 1) * w]
        frows.append([(p[0] / 255.0, p[1] / 255.0, p[2] / 255.0) for p in row])
    stages["float_pack_s"] = time.perf_counter() - t0

    selections = grade.get("selections") or []
    t0 = time.perf_counter()
    for sel in selections:
        if sel.get("qualifier", {}).get("type", "none") not in (None, "none", ""):
            continue
        rasterize_mask_coverage(sel.get("mask") or {}, width=w, height=h)
    stages["mask_raster_all_selections_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    graded = apply_managed_grade_image(frows, grade, lattice_domain="srgb")
    stages["apply_managed_grade_image_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    out = Image.new("RGB", (w, h))
    flat = []
    for row in graded:
        for r, g, b in row:
            flat.append(
                (
                    max(0, min(255, int(round(r * 255)))),
                    max(0, min(255, int(round(g * 255)))),
                    max(0, min(255, int(round(b * 255)))),
                )
            )
    out.putdata(flat)
    dest = OUT / "stage-breakdown-out.jpg"
    out.save(dest, quality=95)
    stages["encode_jpeg_s"] = time.perf_counter() - t0
    stages["total_staged_s"] = sum(stages.values())
    stages["megapixels"] = round((w * h) / 1e6, 3)
    stages["size"] = [w, h]  # type: ignore[assignment]
    os.environ.pop("ORGA_SPATIAL_APPLY_WORKERS", None)
    return stages


def _numpy_desat_prototype(width: int, height: int, runs: int = 5) -> dict:
    """Kernel-only: grayscale via luminance (approx BG desat) on float RGB."""
    try:
        import numpy as np
    except ImportError:
        return {"available": False, "reason": "numpy not installed as project dep"}

    rng = np.random.default_rng(0)
    img = rng.random((height, width, 3), dtype=np.float64)
    mask = rng.random((height, width), dtype=np.float64) > 0.5
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        luma = 0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2]
        gray = np.stack([luma, luma, luma], axis=-1)
        out = np.where(mask[..., None], gray, img)
        _ = float(out.mean())
        times.append(time.perf_counter() - t0)
    return {
        "available": True,
        "op": "numpy_where_desat",
        "size": [width, height],
        "runs": times,
        "median_s": statistics.median(times),
        "mp_per_s": (width * height / 1e6) / statistics.median(times),
    }


def _pure_python_desat_prototype(width: int, height: int, runs: int = 2) -> dict:
    """Kernel-only pure Python desat for language comparison."""
    import random

    random.seed(0)
    img = [
        [(random.random(), random.random(), random.random()) for _ in range(width)]
        for _ in range(height)
    ]
    mask = [[random.random() > 0.5 for _ in range(width)] for _ in range(height)]
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        out = []
        for y in range(height):
            row = []
            for x in range(width):
                r, g, b = img[y][x]
                if mask[y][x]:
                    yv = 0.2126 * r + 0.7152 * g + 0.0722 * b
                    row.append((yv, yv, yv))
                else:
                    row.append((r, g, b))
            out.append(row)
        _ = out[0][0][0]
        times.append(time.perf_counter() - t0)
    return {
        "op": "pure_python_desat",
        "size": [width, height],
        "runs": times,
        "median_s": statistics.median(times),
        "mp_per_s": (width * height / 1e6) / statistics.median(times),
    }


def _write_rust_and_csharp_kernels() -> dict:
    """Emit isolated kernel sources for optional local builds (not production)."""
    rust = OUT / "kernels" / "desat_kernel.rs"
    csharp = OUT / "kernels" / "DesatKernel.cs"
    rust.parent.mkdir(parents=True, exist_ok=True)
    rust.write_text(
        '''// Isolated desat kernel POC (#551) — build with: rustc -O desat_kernel.rs
// Not linked into Orga-Drone.
fn main() {
    let w = 1125usize;
    let h = 1984usize;
    let n = w * h;
    let mut img = vec![0.5f64; n * 3];
    let mask: Vec<bool> = (0..n).map(|i| i % 2 == 0).collect();
    let t0 = std::time::Instant::now();
    for i in 0..n {
        if mask[i] {
            let r = img[i*3];
            let g = img[i*3+1];
            let b = img[i*3+2];
            let y = 0.2126*r + 0.7152*g + 0.0722*b;
            img[i*3] = y; img[i*3+1] = y; img[i*3+2] = y;
        }
    }
    let dt = t0.elapsed().as_secs_f64();
    let mp = (n as f64) / 1e6;
    println!("{{\"lang\":\"rust\",\"median_s\":{dt},\"mp_per_s\":{}}}", mp/dt);
}
''',
        encoding="utf-8",
    )
    csharp.write_text(
        '''// Isolated desat kernel POC (#551) — build with: dotnet script or csc /o
// Not linked into Orga-Drone.
using System;
using System.Diagnostics;
class DesatKernel {
  static void Main() {
    int w=1125, h=1984, n=w*h;
    var img = new double[n*3];
    var mask = new bool[n];
    for (int i=0;i<n;i++){ img[i*3]=img[i*3+1]=img[i*3+2]=0.5; mask[i]= (i%2)==0; }
    var sw = Stopwatch.StartNew();
    for (int i=0;i<n;i++){
      if (!mask[i]) continue;
      double r=img[i*3], g=img[i*3+1], b=img[i*3+2];
      double y=0.2126*r+0.7152*g+0.0722*b;
      img[i*3]=img[i*3+1]=img[i*3+2]=y;
    }
    sw.Stop();
    double dt=sw.Elapsed.TotalSeconds, mp=n/1e6;
    Console.WriteLine($"{{\"lang\":\"csharp\",\"median_s\":{dt},\"mp_per_s\":{mp/dt}}}");
  }
}
''',
        encoding="utf-8",
    )
    results: dict = {"rust_src": str(rust), "csharp_src": str(csharp)}
    # Try rustc / dotnet if present
    import shutil
    import subprocess

    if shutil.which("rustc"):
        exe = OUT / "kernels" / "desat_rust.exe"
        r = subprocess.run(
            ["rustc", "-O", str(rust), "-o", str(exe)],
            capture_output=True,
            text=True,
        )
        results["rustc"] = {"ok": r.returncode == 0, "stderr": r.stderr[-500:]}
        if r.returncode == 0:
            times = []
            for _ in range(3):
                out = subprocess.check_output([str(exe)], text=True)
                times.append(json.loads(out.strip()))
            results["rust_runs"] = times
    else:
        results["rustc"] = {"ok": False, "reason": "rustc not on PATH"}
    if shutil.which("csc") or shutil.which("dotnet"):
        results["csharp_toolchain"] = "present"
    else:
        results["csharp_toolchain"] = "absent"
    return results


def main() -> int:
    assert BEFORE.is_file(), BEFORE
    report: dict = {
        "issue": 551,
        "git_sha": "0034e9257b56a56ba0730364353c36393ad75a5c",
        "before": str(BEFORE),
        "neon_acceptance_export_s": 174.41,
        "machine": {
            "cpu": "AMD Ryzen 7 5700X 8C/16T",
            "ram_gb": 32,
            "gpu": "AMD Radeon RX 6700 XT",
            "os": "Windows 11 Pro 10.0.26300",
            "python": sys.version.split()[0],
        },
    }
    grade, grade_src = _load_or_build_grade()
    report["grade_source"] = grade_src
    report["selection_count"] = len(grade.get("selections") or [])
    report["step_count"] = len(grade.get("steps") or [])
    poly = None
    for sel in grade.get("selections") or []:
        for leaf in (sel.get("mask") or {}).get("leaves") or []:
            if leaf.get("type") == "polygon":
                poly = leaf.get("points")
                break
    report["polygon_vertices"] = len(poly or [])
    (OUT / "neon-grade.json").write_text(json.dumps(grade, indent=2), encoding="utf-8")

    print("=== stage breakdown (workers=1) ===", flush=True)
    report["stage_breakdown"] = _stage_breakdown(grade)
    print(json.dumps(report["stage_breakdown"], indent=2), flush=True)

    print("=== cProfile apply workers=1 ===", flush=True)
    report["cprofile"] = _profile_apply(grade)
    print(report["cprofile"], flush=True)

    print("=== materialize workers=1 (2 runs) ===", flush=True)
    report["materialize_workers_1"] = _timed_materialize(grade, "1", runs=2)
    print(json.dumps(report["materialize_workers_1"], indent=2), flush=True)

    print("=== materialize workers=auto (3 runs) ===", flush=True)
    report["materialize_workers_auto"] = _timed_materialize(grade, None, runs=3)
    print(json.dumps(report["materialize_workers_auto"], indent=2), flush=True)

    print("=== materialize workers=8 (3 runs) ===", flush=True)
    report["materialize_workers_8"] = _timed_materialize(grade, "8", runs=3)
    print(json.dumps(report["materialize_workers_8"], indent=2), flush=True)

    # Kernel microbenches at Neon resolution and scaled sizes
    sizes = [(1125, 1984), (2000, 4000), (3000, 4000), (4000, 6000)]
    kernels = []
    for w, h in sizes:
        # Downscale pure-python for large sizes to keep wall time sane: sample one size fully
        if w * h > 1125 * 1984:
            py = _pure_python_desat_prototype(min(w, 800), min(h, 800), runs=1)
            py["note"] = "downscaled pure-python sample"
        else:
            py = _pure_python_desat_prototype(w, h, runs=2)
        npk = _numpy_desat_prototype(w, h, runs=5)
        kernels.append({"size": [w, h], "python": py, "numpy": npk})
    report["kernel_desat"] = kernels
    report["native_kernel_sources"] = _write_rust_and_csharp_kernels()

    (OUT / "investigation-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print("Wrote", OUT / "investigation-report.json", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
