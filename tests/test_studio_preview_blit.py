"""Studio preview blit stays sharp without softening privacy pixelate."""

from pathlib import Path


def _slice(script: str, start: str, end: str) -> str:
    body = script.split(start, 1)[1]
    return body.split(end, 1)[0]


def test_preview_blit_uses_device_pixels_and_smoothing() -> None:
    script = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    ratio = _slice(script, "function previewBackingRatio", "function readPreviewTransform")
    paint = _slice(script, "function paintPreviewBlit", "function schedulePreviewBlit")
    draw = _slice(script, "function drawPreviewLayer", "function ensurePreviewBlit")
    mask = _slice(script, "function paintPrivacyMask", "function drawMaskCanvas")

    assert "devicePixelRatio" in ratio
    assert "Math.min(dpr, 3)" in ratio
    assert "4096" in ratio
    assert "previewBackingRatio(cssW, cssH)" in paint
    assert "canvas.width = pixelW" in paint
    assert "canvas.height = pixelH" in paint
    assert "imageSmoothingEnabled = true" in paint
    assert 'imageSmoothingQuality = "high"' in draw
    assert "imageSmoothingEnabled = false" in mask
