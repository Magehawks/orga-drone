#!/usr/bin/env python3
"""Measure HTTP ping latency while a spatial photo bake runs (#513 / #506).

Compares in-process (ORGA_SPATIAL_BAKE_INLINE=1) vs process worker (default).
Uses a lightweight ThreadingHTTPServer in the parent to sample latency while
``materialize_spatial_managed_media`` runs on a background thread.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from orga_drone.studio_managed_spatial_export import materialize_spatial_managed_media


class _Ping(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def _grade() -> dict:
    strokes = []
    for i in range(12):
        x = 0.3 + i * 0.03
        strokes.append(
            {
                "mode": "add",
                "radius": 0.05,
                "hardness": 0.75,
                "points": [[x, 0.45], [x + 0.01, 0.6], [x, 0.75]],
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
                "id": "a",
                "type": "primaries-v1",
                "enabled": True,
                "mix": 1.0,
                "selection_id": "leaf",
                "params": {
                    "exposure": 0.05,
                    "kelvin": 4200,
                    "tint": 90,
                    "contrast": 1.08,
                    "pivot": 0.42,
                    "saturation": 1.5,
                    "blacks": -5,
                    "shadows": 10,
                    "highlights": -30,
                    "whites": -20,
                },
            }
        ],
        "selections": [
            {
                "id": "leaf",
                "invert": False,
                "mask": {
                    "combine": "union",
                    "leaves": [{"type": "brush", "feather": 0.03, "strokes": strokes}],
                },
                "qualifier": {"type": "none"},
            }
        ],
        "animation": [],
        "output": {"profile": "bt709-sdr", "gamut": "clip"},
        "extensions": {},
    }


def _sample(url: str) -> float:
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=2.0) as resp:
            resp.read(8)
        return (time.perf_counter() - t0) * 1000.0
    except Exception:
        return float("nan")


def _run(*, width: int, height: int, inline: bool) -> dict:
    os.environ["ORGA_SPATIAL_BAKE_INLINE"] = "1" if inline else "0"
    os.environ.pop("ORGA_SPATIAL_BAKE_PROCESS", None)
    if not inline:
        os.environ["ORGA_SPATIAL_BAKE_PROCESS"] = "1"

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Ping)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    done = threading.Event()
    bake_s = {"v": None}
    samples: list[float] = []

    with tempfile.TemporaryDirectory(prefix="orga-http-bake-") as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "s.jpg"
        Image.new("RGB", (width, height), (70, 50, 30)).save(src, quality=90)

        def _bake() -> None:
            try:
                t0 = time.perf_counter()
                materialize_spatial_managed_media(
                    src,
                    _grade(),
                    tmp_path / "work",
                    kind="photo",
                    grade_digest=f"httpbench{width}x{height}",
                )
                bake_s["v"] = time.perf_counter() - t0
            finally:
                done.set()

        threading.Thread(target=_bake, daemon=True).start()
        while not done.wait(0.05):
            samples.append(_sample(url))
        # a few more after finish
        for _ in range(5):
            samples.append(_sample(url))
            time.sleep(0.02)

    server.shutdown()
    finite = [x for x in samples if x == x]
    return {
        "inline": inline,
        "width": width,
        "height": height,
        "bake_s": bake_s["v"],
        "http_samples": len(samples),
        "http_ok": len(finite),
        "http_p50_ms": statistics.median(finite) if finite else None,
        "http_p95_ms": (
            statistics.quantiles(finite, n=20)[18] if len(finite) >= 20 else max(finite)
        )
        if finite
        else None,
        "http_max_ms": max(finite) if finite else None,
    }


def main() -> int:
    rows = [
        _run(width=256, height=256, inline=True),
        _run(width=256, height=256, inline=False),
    ]
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
