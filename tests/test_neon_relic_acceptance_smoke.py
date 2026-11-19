"""Smoke: Neon Relic acceptance harness grades a tiny synthetic photo (#514)."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "neon_relic_creative_acceptance.py"


def _load():
    spec = importlib.util.spec_from_file_location("neon_relic_creative_acceptance", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_neon_relic_harness_tiny_bake(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ORGA_SPATIAL_BAKE_INLINE", "1")
    mod = _load()
    src = tmp_path / "before.jpg"
    Image.new("RGB", (48, 64), (40, 80, 30)).save(src, quality=90)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    # Call materialize path used by the script (avoid full CLI defaults).
    os.environ["ORGA_SPATIAL_BAKE_INLINE"] = "1"
    graded = mod.materialize_spatial_managed_media(
        src,
        mod._grade(),
        tmp_path / "work",
        kind="photo",
        grade_digest="neonrelic514smoke",
    )
    assert graded.is_file() and graded.stat().st_size > 0
    means = mod._channel_means(graded)
    assert means["r"] >= 0 and means["g"] >= 0 and means["b"] >= 0
