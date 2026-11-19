#!/usr/bin/env python3
"""Neon Relic creative acceptance via Orga-Drone managed grade APIs (#514).

Uses BEFORE fixture (or --source), applies brush leaf + invert BG magenta/BW
grade through ``materialize_spatial_managed_media`` + JPEG publish (same CPU
path as Studio still export), writes evidence JPG + JSON metrics vs TARGET.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from orga_drone.studio_managed_spatial_export import materialize_spatial_managed_media


def _leaf_strokes() -> list[dict]:
    # Dense vertical strips approximating the main leaf body (normalized UV).
    strokes = []
    for i in range(28):
        x = 0.22 + i * (0.52 / 27)
        y0 = 0.42 + 0.08 * abs((i / 27) - 0.5)
        y1 = 0.88 - 0.05 * abs((i / 27) - 0.35)
        mid = (y0 + y1) / 2
        strokes.append(
            {
                "mode": "add",
                "radius": 0.035 + 0.01 * (1 - abs((i / 27) - 0.45)),
                "hardness": 0.82,
                "points": [[x, y0], [x + 0.008, mid], [x, y1]],
            }
        )
    return strokes


def _grade() -> dict:
    strokes = _leaf_strokes()
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
                "selection_id": "sel-leaf-brush",
                "params": {
                    "exposure": 0.04,
                    "kelvin": 4000,
                    "tint": 100,
                    "contrast": 1.1,
                    "pivot": 0.4,
                    "saturation": 1.45,
                    "blacks": -8,
                    "shadows": 12,
                    "highlights": -45,
                    "whites": -30,
                },
            },
            {
                "id": "hsl-bg",
                "type": "managed-hsl-v1",
                "enabled": True,
                "mix": 1.0,
                "selection_id": "sel-bg-invert",
                "params": {"hue": 0, "saturation": 0.0, "lightness": -0.08},
            },
        ],
        "selections": [
            {
                "id": "sel-leaf-brush",
                "invert": False,
                "mask": {
                    "combine": "union",
                    "leaves": [{"type": "brush", "feather": 0.025, "strokes": strokes}],
                },
                "qualifier": {"type": "none"},
            },
            {
                "id": "sel-bg-invert",
                "invert": True,
                "mask": {
                    "combine": "union",
                    "leaves": [{"type": "brush", "feather": 0.025, "strokes": strokes}],
                },
                "qualifier": {"type": "none"},
            },
        ],
        "animation": [],
        "output": {"profile": "bt709-sdr", "gamut": "clip"},
        "extensions": {},
    }


def _channel_means(path: Path) -> dict[str, float]:
    with Image.open(path) as im:
        rgb = im.convert("RGB")
        stat = ImageStat.Stat(rgb)
        return {"r": stat.mean[0], "g": stat.mean[1], "b": stat.mean[2]}


def _chroma_ratio(means: dict[str, float]) -> float:
    r, g, b = means["r"], means["g"], means["b"]
    mx = max(r, g, b) + 1e-6
    return (abs(r - g) + abs(g - b) + abs(b - r)) / (3.0 * mx)


def _default_evidence_dir() -> Path | None:
    env = os.environ.get("ORGA_NEON_RELIC_DIR", "").strip()
    if env:
        return Path(env)
    # Common local worktree used for #506 acceptance (not committed).
    candidate = (
        Path.home()
        / "Projects"
        / "orga-drone-wt"
        / "exe-build-develop-083ec12"
        / "acceptance-evidence"
        / "neon-relic"
    )
    return candidate if candidate.is_dir() else None


def main() -> int:
    evidence = _default_evidence_dir()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=(evidence / "00-before-original.jpg") if evidence else None,
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=(
            (evidence / "Magenta Blatt mit Regentropfen.png") if evidence else None
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=evidence,
    )
    args = parser.parse_args()
    if args.source is None or not args.source.is_file():
        print(
            "missing source; pass --source or set ORGA_NEON_RELIC_DIR",
            file=sys.stderr,
        )
        return 2
    if args.out_dir is None:
        print("missing --out-dir / ORGA_NEON_RELIC_DIR", file=sys.stderr)
        return 2

    os.environ.setdefault("ORGA_SPATIAL_BAKE_PROCESS", "1")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_jpg = args.out_dir / "20-neon-relic-orga-export.jpg"
    out_json = args.out_dir / "20-neon-relic-orga-export.json"

    with tempfile.TemporaryDirectory(prefix="neon-relic-") as tmp:
        work = Path(tmp) / "work"
        t0 = __import__("time").perf_counter()
        graded = materialize_spatial_managed_media(
            args.source,
            _grade(),
            work,
            kind="photo",
            grade_digest="neonrelic514accept01",
        )
        elapsed = __import__("time").perf_counter() - t0
        with Image.open(graded) as im:
            rgb = im.convert("RGB")
            rgb.save(out_jpg, format="JPEG", quality=92, optimize=True)

    result_means = _channel_means(out_jpg)
    target_means = _channel_means(args.target) if args.target.is_file() else None
    payload = {
        "issue": 514,
        "parent": 506,
        "source": str(args.source),
        "output": str(out_jpg),
        "bake_s": round(elapsed, 2),
        "result_means": result_means,
        "result_chroma_ratio": round(_chroma_ratio(result_means), 4),
        "target_means": target_means,
        "target_chroma_ratio": (
            round(_chroma_ratio(target_means), 4) if target_means else None
        ),
        "notes": [
            "Grade via Orga-Drone materialize_spatial_managed_media (Studio still path).",
            "Brush mask approximates leaf; not AI freistellung — edge fidelity limited.",
            "Magenta via primaries tint/kelvin; BG desat via inverted selection HSL.",
        ],
    }
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
