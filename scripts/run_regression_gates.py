#!/usr/bin/env python3
"""Run the curated creator regression gate suite (#275/#283/#284)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "tests" / "fixtures" / "regression_gate_modules.json"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    src = str(ROOT / "src")
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src if not prev else src + os.pathsep + prev
    return env


def main() -> int:
    payload = json.loads(MODULES.read_text(encoding="utf-8"))
    python_tests = [
        rel
        for rel in payload["python_modules"]
        if rel.startswith("tests/") and rel.endswith(".py")
    ]
    js_tests = list(payload["js_modules"])
    print("Creator regression gates — Python")
    print("PYTHONPATH includes", ROOT / "src")
    py = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short", *python_tests],
        cwd=ROOT,
        env=_env(),
    )
    if py.returncode != 0:
        return py.returncode
    print("Creator regression gates — scopes accumulate JS")
    js = subprocess.run(["node", "--test", *js_tests], cwd=ROOT, env=_env())
    return js.returncode


if __name__ == "__main__":
    raise SystemExit(main())
