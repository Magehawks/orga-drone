"""Smoke import + tiny spatial bake for the #507 harness."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bench_spatial_grade.py"


def _load_bench_module():
    spec = importlib.util.spec_from_file_location("bench_spatial_grade", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_spatial_bench_smoke_32px(tmp_path: Path) -> None:
    mod = _load_bench_module()
    source = mod._write_synthetic(tmp_path / "s.jpg", 32, 32)
    grade = mod._brush_leaf_grade()
    graded, elapsed = mod._run_once(source, tmp_path / "work", grade)
    assert graded.is_file() and graded.stat().st_size > 0
    assert elapsed < 30.0  # pure-Python; keep generous for CI hosts
    payload = {
        "width": 32,
        "height": 32,
        "seconds": elapsed,
        "issue": 507,
    }
    (tmp_path / "smoke.json").write_text(json.dumps(payload), encoding="utf-8")
