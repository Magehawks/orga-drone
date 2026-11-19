"""Smoke for #513 HTTP-during-bake harness (tiny inline bake)."""

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


def test_http_during_bake_smoke_inline(monkeypatch) -> None:
    monkeypatch.setenv("ORGA_SPATIAL_BAKE_INLINE", "1")
    mod = _load()
    # Keep CI cheap: tiny image, inline path only.
    row = mod._run(width=32, height=32, inline=True)
    assert row["http_ok"] >= 1
    assert row["bake_s"] is not None and row["bake_s"] < 60.0
    assert row["http_p50_ms"] is not None
