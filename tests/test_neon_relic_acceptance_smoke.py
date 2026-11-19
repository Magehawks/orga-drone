"""Smoke: Neon Relic acceptance CLI grades a tiny synthetic photo (#514)."""

from __future__ import annotations

import importlib.util
import json
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


def test_neon_relic_main_writes_jpeg_and_metrics(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ORGA_SPATIAL_BAKE_INLINE", "1")
    monkeypatch.delenv("ORGA_NEON_RELIC_DIR", raising=False)
    mod = _load()
    src = tmp_path / "before.jpg"
    Image.new("RGB", (48, 64), (40, 80, 30)).save(src, quality=90)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(
        "sys.argv",
        [
            "neon_relic_creative_acceptance.py",
            "--source",
            str(src),
            "--out-dir",
            str(out_dir),
        ],
    )
    assert mod.main() == 0
    jpg = out_dir / "20-neon-relic-orga-export.jpg"
    meta = out_dir / "20-neon-relic-orga-export.json"
    assert jpg.is_file() and jpg.stat().st_size > 0
    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert payload["issue"] == 514
    assert payload["result_means"]["r"] >= 0
    # Grade should not be a byte-identical copy of the flat source fill.
    assert jpg.read_bytes() != src.read_bytes()
