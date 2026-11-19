"""Smoke for #513 HTTP-during-bake harness (inline vs process worker)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bench_spatial_http_during_bake.py"


def _load():
    spec = importlib.util.spec_from_file_location("bench_spatial_http_during_bake", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_http_during_bake_worker_beats_inline_tail() -> None:
    """Lock hang-class regression: process worker keeps HTTP p95 well below inline.

    96×96 meets the process-isolation pixel threshold used in production code.
    Bounds stay loose for CI hosts.
    """
    mod = _load()
    inline = mod._run(width=96, height=96, inline=True)
    worker = mod._run(width=96, height=96, inline=False)
    assert inline["http_ok"] >= 1 and worker["http_ok"] >= 1
    assert inline["http_p95_ms"] is not None and worker["http_p95_ms"] is not None
    assert inline["bake_s"] is not None and inline["bake_s"] < 120.0
    assert worker["bake_s"] is not None and worker["bake_s"] < 120.0
    # Worker must not show the multi-hundred-ms GIL starvation tail.
    assert worker["http_p95_ms"] < 50.0
    assert worker["http_p95_ms"] < inline["http_p95_ms"]
