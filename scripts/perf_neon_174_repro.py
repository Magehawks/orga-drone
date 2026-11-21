#!/usr/bin/env python3
"""Reproduce the ~174s Neon Relic export conditions (#551)."""

from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_DEFAULT_BEFORE = Path(
    r"C:\Users\Niwes\Projects\orga-drone-wt\precision-mask-develop"
    r"\acceptance-evidence\neon-relic\00-before-original.jpg"
)
BEFORE = Path(os.environ.get("ORGA_PERF_BEFORE", str(_DEFAULT_BEFORE)))
OUT = ROOT / "docs" / "performance" / "evidence" / "photo-render-investigation"


def build_grade() -> dict:
    from orga_drone.studio_object_select import propose_object_polygon

    seeds = [(0.42, 0.70), (0.48, 0.72), (0.52, 0.68), (0.45, 0.78), (0.55, 0.75)]
    best = None
    for u, v in seeds:
        try:
            prop = propose_object_polygon(BEFORE, u, v, max_edge=640, tol=16.0)
        except Exception as exc:
            print("seed fail", (u, v), exc, flush=True)
            continue
        cov = prop.coverage
        score = cov if 0.12 <= cov <= 0.55 else -abs(cov - 0.30)
        if best is None or score > best[0]:
            best = (score, prop.points, (u, v), cov, len(prop.points))
    if best is None:
        # Fall back to acceptance-grade polygon if live proposal fails.
        cached = OUT / "neon-grade.json"
        grade_cached = json.loads(cached.read_text(encoding="utf-8"))
        for sel in grade_cached.get("selections") or []:
            for leaf in (sel.get("mask") or {}).get("leaves") or []:
                if leaf.get("type") == "polygon" and leaf.get("points"):
                    pts = leaf["points"]
                    best = (0.0, pts, ("cached", 0), 0.0, len(pts))
                    break
    assert best, "no polygon available"
    points = best[1]
    leaf = {
        "id": "sel-leaf",
        "name": "Blatt",
        "invert": False,
        "mask": {
            "combine": "union",
            "leaves": [
                {"type": "polygon", "points": points, "feather": 0.015, "closed": True}
            ],
        },
        "qualifier": {"type": "none"},
    }
    bg = {
        "id": "sel-bg",
        "name": "Hintergrund",
        "invert": True,
        "mask": leaf["mask"],
        "qualifier": {"type": "none"},
    }
    grade = {
        "schema_version": 1,
        "evaluator": "managed-sdr-v1",
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
    }
    meta = {"seed": best[2], "coverage": best[3], "vertices": best[4]}
    return grade, meta


def bench(grade: dict, workers: str, bake_inline: bool, runs: int = 2) -> dict:
    from orga_drone.studio_managed_spatial_export import materialize_spatial_managed_media

    os.environ["ORGA_SPATIAL_APPLY_WORKERS"] = workers
    if bake_inline:
        os.environ["ORGA_SPATIAL_BAKE_INLINE"] = "1"
    else:
        os.environ.pop("ORGA_SPATIAL_BAKE_INLINE", None)
    times = []
    for i in range(runs):
        with tempfile.TemporaryDirectory() as tmp:
            t0 = time.perf_counter()
            materialize_spatial_managed_media(
                BEFORE,
                grade,
                Path(tmp),
                kind="photo",
                grade_digest=f"neon174-{workers}-{bake_inline}-{i}",
            )
            times.append(time.perf_counter() - t0)
            print(
                f"workers={workers} inline={bake_inline} run={i} {times[-1]:.3f}s",
                flush=True,
            )
    return {
        "workers": workers,
        "bake_inline": bake_inline,
        "runs": times,
        "median": statistics.median(times),
        "min": min(times),
        "max": max(times),
    }


def main() -> int:
    grade, meta = build_grade()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "neon174-grade.json").write_text(json.dumps(grade, indent=2), encoding="utf-8")
    print("meta", meta, flush=True)
    results = {
        "meta": meta,
        "acceptance_export_s": 174.41,
        "configs": [
            bench(grade, "1", False, runs=2),
            bench(grade, "1", True, runs=2),
            bench(grade, "8", True, runs=3),
        ],
    }
    (OUT / "neon174-repro.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
