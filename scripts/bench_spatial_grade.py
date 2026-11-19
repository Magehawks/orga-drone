#!/usr/bin/env python3
"""Reproducible spatial managed-grade bake benchmark (#507 / #506).

Measures wall time, optional cProfile hotspots, and a simple HTTP ping latency
while a bake occupies a worker thread (simulates Studio starvation class).

No private media required: synthetic RGB photos at requested sizes.
Optional --source path for local Neon Relic BEFORE runs (not committed).
"""

from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import statistics
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path

from PIL import Image

# Allow `python scripts/bench_spatial_grade.py` from a checkout without install.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from orga_drone.studio_managed_spatial_export import (  # noqa: E402
    materialize_spatial_managed_media,
)


def _brush_leaf_grade() -> dict:
    """Compact brush+invert grade similar to Neon Relic Rev71 shape (synthetic)."""
    strokes = []
    # Vertical strips approximating a leaf body (normalized UV).
    for i in range(18):
        x = 0.28 + i * 0.025
        strokes.append(
            {
                "mode": "add",
                "radius": 0.04,
                "hardness": 0.78,
                "points": [[x, 0.55], [x + 0.01, 0.68], [x, 0.80]],
            }
        )
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
                    "exposure": 0.05,
                    "kelvin": 4200,
                    "tint": 100,
                    "contrast": 1.08,
                    "pivot": 0.42,
                    "saturation": 1.55,
                    "blacks": -5,
                    "shadows": 15,
                    "highlights": -40,
                    "whites": -35,
                },
            },
            {
                "id": "hsl-bg",
                "type": "managed-hsl-v1",
                "enabled": True,
                "mix": 1.0,
                "selection_id": "sel-bg-invert",
                "params": {"hue": 0, "saturation": 0.0, "lightness": -0.06},
            },
        ],
        "selections": [
            {
                "id": "sel-leaf-brush",
                "invert": False,
                "mask": {
                    "combine": "union",
                    "leaves": [{"type": "brush", "feather": 0.03, "strokes": strokes}],
                },
                "qualifier": None,
            },
            {
                "id": "sel-bg-invert",
                "invert": True,
                "mask": {
                    "combine": "union",
                    "leaves": [{"type": "brush", "feather": 0.03, "strokes": strokes}],
                },
                "qualifier": None,
            },
        ],
        "animation": [],
        "output": {"profile": "bt709-sdr", "gamut": "clip"},
        "extensions": {},
    }


def _write_synthetic(path: Path, width: int, height: int) -> Path:
    # Fast deterministic gradient (no private pixels). Avoid Python per-pixel loops.
    img = Image.new("RGB", (width, height))
    # Horizontal blend via resize from a 2-stop ramp.
    ramp = Image.new("RGB", (2, 2))
    ramp.putdata([(40, 30, 20), (200, 30, 20), (40, 150, 20), (200, 150, 100)])
    img = ramp.resize((width, height), Image.Resampling.BILINEAR)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="JPEG", quality=92)
    return path


class _PingHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def _http_latencies_ms(url: str, samples: int, pause_s: float) -> list[float]:
    import urllib.request

    out: list[float] = []
    for _ in range(samples):
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                resp.read(16)
            out.append((time.perf_counter() - t0) * 1000.0)
        except Exception:
            out.append(float("nan"))
        time.sleep(pause_s)
    return out


def _run_once(source: Path, work: Path, grade: dict) -> tuple[Path, float]:
    # Unique work dir per run so cache hits do not hide bake cost unless requested.
    t0 = time.perf_counter()
    graded = materialize_spatial_managed_media(
        source,
        grade,
        work,
        kind="photo",
        grade_digest=None,
    )
    return graded, time.perf_counter() - t0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, default=1125)
    parser.add_argument("--height", type=int, default=1984)
    parser.add_argument("--source", type=Path, default=None, help="Optional local JPEG/PNG")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--http-contention", action="store_true")
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    grade = _brush_leaf_grade()
    with tempfile.TemporaryDirectory(prefix="orga-spatial-bench-") as tmp:
        tmp_path = Path(tmp)
        if args.source is not None:
            source = args.source
            with Image.open(source) as im:
                width, height = im.size
        else:
            width, height = args.width, args.height
            source = _write_synthetic(tmp_path / "source.jpg", width, height)

        times: list[float] = []
        profile_top = ""
        http_stats: dict | None = None

        for i in range(max(1, args.runs)):
            work = tmp_path / f"work-{i}"
            work.mkdir(parents=True, exist_ok=True)

            if args.http_contention and i == 0:
                server = ThreadingHTTPServer(("127.0.0.1", 0), _PingHandler)
                port = server.server_address[1]
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                bake_done = threading.Event()
                latencies: list[float] = []

                def _bake() -> None:
                    nonlocal times
                    try:
                        if args.profile:
                            pr = cProfile.Profile()
                            pr.enable()
                            _graded, elapsed = _run_once(source, work, grade)
                            pr.disable()
                            buf = StringIO()
                            stats = pstats.Stats(pr, stream=buf).sort_stats("cumulative")
                            stats.print_stats(25)
                            nonlocal profile_top
                            profile_top = buf.getvalue()
                            times.append(elapsed)
                        else:
                            _graded, elapsed = _run_once(source, work, grade)
                            times.append(elapsed)
                    finally:
                        bake_done.set()

                worker = threading.Thread(target=_bake, daemon=True)
                worker.start()
                # Sample while bake runs.
                while not bake_done.wait(0.05):
                    latencies.extend(
                        _http_latencies_ms(f"http://127.0.0.1:{port}/", samples=1, pause_s=0.0)
                    )
                worker.join()
                server.shutdown()
                finite = [x for x in latencies if x == x]
                http_stats = {
                    "samples": len(latencies),
                    "ok": len(finite),
                    "p50_ms": statistics.median(finite) if finite else None,
                    "p95_ms": (
                        statistics.quantiles(finite, n=20)[18]
                        if len(finite) >= 20
                        else (max(finite) if finite else None)
                    ),
                    "max_ms": max(finite) if finite else None,
                }
            elif args.profile and i == 0:
                pr = cProfile.Profile()
                pr.enable()
                _graded, elapsed = _run_once(source, work, grade)
                pr.disable()
                buf = StringIO()
                pstats.Stats(pr, stream=buf).sort_stats("cumulative").print_stats(25)
                profile_top = buf.getvalue()
                times.append(elapsed)
            else:
                _graded, elapsed = _run_once(source, work, grade)
                times.append(elapsed)

        result = {
            "issue": 507,
            "parent": 506,
            "source": str(source),
            "width": width,
            "height": height,
            "pixels": width * height,
            "runs": times,
            "seconds_mean": statistics.mean(times),
            "seconds_min": min(times),
            "seconds_max": max(times),
            "mpixel_per_s": (width * height / max(1e-9, statistics.mean(times))) / 1e6,
            "http_contention": http_stats,
            "profile_top": profile_top,
        }
        text = json.dumps({k: v for k, v in result.items() if k != "profile_top"}, indent=2)
        print(text)
        if profile_top:
            print("\n--- cProfile (cumulative top 25) ---\n")
            print(profile_top)
        if args.json_out is not None:
            payload = dict(result)
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
