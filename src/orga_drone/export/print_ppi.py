"""Effective PPI helper for photo print-size guidance (issue #450).

This is educational math only. It does not upscale pixels, write DPI tags, or
promise print-shop quality.
"""

from __future__ import annotations

from dataclasses import dataclass

MM_PER_INCH = 25.4


@dataclass(frozen=True)
class PrintSizePreset:
    """Physical paper size in millimetres (short side × long side as listed)."""

    id: str
    width_mm: float
    height_mm: float

    def as_dict(self) -> dict[str, float | str]:
        return {
            "id": self.id,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
        }


# Common consumer print sizes. Orientation is adjusted to the image in
# ``orient_print_size``.
PRINT_SIZE_PRESETS: tuple[PrintSizePreset, ...] = (
    PrintSizePreset("10x15cm", 100.0, 150.0),
    PrintSizePreset("13x18cm", 130.0, 180.0),
    PrintSizePreset("20x30cm", 200.0, 300.0),
    PrintSizePreset("30x40cm", 300.0, 400.0),
    PrintSizePreset("a4", 210.0, 297.0),
    PrintSizePreset("a3", 297.0, 420.0),
)


def print_size_presets_payload() -> list[dict[str, float | str]]:
    return [preset.as_dict() for preset in PRINT_SIZE_PRESETS]


def orient_print_size(
    export_w: int,
    export_h: int,
    width_mm: float,
    height_mm: float,
) -> tuple[float, float]:
    """Align the long sides of the paper with the long side of the image."""
    w_mm = float(width_mm)
    h_mm = float(height_mm)
    if export_w <= 0 or export_h <= 0 or w_mm <= 0 or h_mm <= 0:
        raise ValueError("Print size and pixel size must be positive.")
    image_landscape = export_w >= export_h
    paper_landscape = w_mm >= h_mm
    if image_landscape == paper_landscape:
        return w_mm, h_mm
    return h_mm, w_mm


def effective_ppi(
    export_w: int,
    export_h: int,
    width_mm: float,
    height_mm: float,
    *,
    orient: bool = True,
) -> float:
    """Minimum PPI that fills the chosen paper from the export pixel grid.

    Uses ``min(px/in)`` so the tighter axis sets the effective density.
    """
    w_px = int(export_w)
    h_px = int(export_h)
    if orient:
        width_mm, height_mm = orient_print_size(w_px, h_px, width_mm, height_mm)
    else:
        width_mm = float(width_mm)
        height_mm = float(height_mm)
    if w_px <= 0 or h_px <= 0 or width_mm <= 0 or height_mm <= 0:
        raise ValueError("Print size and pixel size must be positive.")
    width_in = width_mm / MM_PER_INCH
    height_in = height_mm / MM_PER_INCH
    return min(w_px / width_in, h_px / height_in)


def aspect_ratio_mismatch(
    export_w: int,
    export_h: int,
    width_mm: float,
    height_mm: float,
    *,
    tolerance: float = 0.02,
) -> bool:
    """True when paper and image aspect differ beyond ``tolerance`` (relative)."""
    w_mm, h_mm = orient_print_size(export_w, export_h, width_mm, height_mm)
    image_ar = float(export_w) / float(export_h)
    paper_ar = w_mm / h_mm
    return abs(image_ar - paper_ar) / max(image_ar, paper_ar) > tolerance
