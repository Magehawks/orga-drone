"""Run the real browser scheduling functions with a deterministic event loop."""
import shutil
import subprocess

import pytest


def test_lut_preview_lifecycle() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for browser lifecycle regression")
    subprocess.run([node, "tests/js/lut_preview.cjs"], check=True, timeout=20)


def test_lut_proxy_mapping_and_audio() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for proxy playback regression")
    for script in (
        "tests/js/lut_proxy_mapping.cjs",
        "tests/js/lut_proxy_audio.cjs",
        "tests/js/lut_proxy_auto_prepare.cjs",
        "tests/js/color_playback_proxy.cjs",
    ):
        subprocess.run([node, script], check=True, timeout=20)
