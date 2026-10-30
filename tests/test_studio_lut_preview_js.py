"""Run the real browser scheduling functions with a deterministic event loop."""
import shutil
import subprocess

import pytest


def test_lut_preview_lifecycle() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for browser lifecycle regression")
    subprocess.run([node, "tests/js/lut_preview.cjs"], check=True, timeout=20)
