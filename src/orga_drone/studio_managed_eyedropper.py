"""Eyedropper sample from Studio preview stills (#357).

Returns sample metadata only. Never mutates a grade — the UI must send an
explicit accepted command to change qualifier ranges.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from orga_drone.studio_managed_qualifiers import (
    ManagedQualifierError,
    encoded_luma,
    eyedropper_sample,
    rgb_to_hsl,
)

Rgb = tuple[float, float, float]


class ManagedEyedropperError(Exception):
    def __init__(self, message: str, *, code: str = "EYEDROPPER") -> None:
        super().__init__(message)
        self.code = code


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def sample_preview_jpeg(
    path: Path,
    *,
    u: float,
    v: float,
    neighborhood: float = 0.01,
) -> tuple[Rgb, tuple[float, float, float, float], tuple[int, int]]:
    """Sample a JPEG still at normalized UV with an optional neighborhood box.

    Returns ``(mean_rgb, neighborhood_uv_box, (width, height))``.
    """
    if not path.is_file():
        raise ManagedEyedropperError("preview frame is missing", code="STALE_FRAME")
    if not 0.0 <= u <= 1.0 or not 0.0 <= v <= 1.0:
        raise ManagedEyedropperError("sample UV must be from 0 to 1", code="RANGE")
    radius = _clamp01(neighborhood)
    from PIL import Image

    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        if width < 1 or height < 1:
            raise ManagedEyedropperError("preview frame is empty", code="STALE_FRAME")
        x0 = int(max(0, min(width - 1, round((u - radius) * width))))
        x1 = int(max(0, min(width - 1, round((u + radius) * width))))
        y0 = int(max(0, min(height - 1, round((v - radius) * height))))
        y1 = int(max(0, min(height - 1, round((v + radius) * height))))
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        total_r = total_g = total_b = 0.0
        count = 0
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                pixel = rgb.getpixel((x, y))
                if not isinstance(pixel, tuple) or len(pixel) < 3:
                    continue
                total_r += pixel[0] / 255.0
                total_g += pixel[1] / 255.0
                total_b += pixel[2] / 255.0
                count += 1
        if count <= 0:
            raise ManagedEyedropperError("invalid sample region", code="RANGE")
        mean = (total_r / count, total_g / count, total_b / count)
        box = (
            x0 / width,
            y0 / height,
            (x1 + 1) / width,
            (y1 + 1) / height,
        )
        return mean, box, (width, height)


def qualifier_ranges_from_sample(
    rgb: Rgb,
    *,
    domain: str,
    kind: str,
    softness: float = 0.08,
) -> dict[str, Any]:
    """Build an editable qualifier object from an accepted sample."""
    soft = _clamp01(softness)
    if kind == "rgb":
        channels = []
        for channel in rgb:
            inner = _clamp01(channel)
            outer = min(1.0, soft + 0.02)
            channels.append([inner, outer])
        return {"type": "rgb", "channels": channels}
    if kind == "hsl":
        hue, sat, light = rgb_to_hsl(rgb)
        return {
            "type": "hsl",
            "hue": [float(hue), max(8.0, soft * 180.0)],
            "saturation": [_clamp01(sat), soft],
            "lightness": [_clamp01(light), soft],
        }
    if kind == "luma":
        luma = encoded_luma(rgb)
        return {
            "type": "luma",
            "inner": _clamp01(luma),
            "outer": soft + 0.02,
        }
    raise ManagedEyedropperError(f"unsupported qualifier kind: {kind}", code="RANGE")


def build_eyedropper_payload(
    *,
    rgb: Rgb,
    frame: int,
    revision: int,
    domain: str,
    neighborhood: tuple[float, float, float, float],
    source_time_s: float,
    size: tuple[int, int],
) -> dict[str, Any]:
    """Compose the contract sample payload (no grade mutation)."""
    try:
        sample = eyedropper_sample(
            rgb,
            frame=frame,
            revision=revision,
            domain=domain,
            neighborhood=neighborhood,
        )
    except ManagedQualifierError as exc:
        raise ManagedEyedropperError(str(exc), code=exc.code) from exc
    sample["source_time_s"] = float(source_time_s)
    sample["width"] = int(size[0])
    sample["height"] = int(size[1])
    sample["suggested"] = {
        "rgb": qualifier_ranges_from_sample(rgb, domain=domain, kind="rgb"),
        "hsl": qualifier_ranges_from_sample(rgb, domain=domain, kind="hsl"),
        "luma": qualifier_ranges_from_sample(rgb, domain=domain, kind="luma"),
    }
    return sample


def apply_sample_to_selection(
    selection: Mapping[str, Any] | None,
    qualifier: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a selection copy with the accepted qualifier (explicit UI accept)."""
    next_sel = dict(selection or {})
    if "id" not in next_sel:
        raise ManagedEyedropperError("selection id is required", code="RANGE")
    next_sel["qualifier"] = dict(qualifier)
    if "mask" not in next_sel:
        next_sel["mask"] = {"combine": "union", "leaves": []}
    if "invert" not in next_sel:
        next_sel["invert"] = False
    return next_sel
