"""Optional sharpen and denoise after the Studio grade (Issue #177).

Values live in ``effect_settings.detail``. Both default to off (0). Export uses
bundled FFmpeg ``unsharp`` then ``hqdn3d`` after grade/LUT and before the
saturation ramp. Preview is a coarse CSS approximation only. Source files stay
unchanged.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Mapping

DETAIL_KEY = "detail"
SLIDER_MIN = 0
SLIDER_MAX = 100
# Restrained full-scale amounts — avoid harsh halos / smearing by default.
SHARPEN_AMOUNT_AT_FULL = 0.8
DENOISE_LUMA_AT_FULL = 3.0
DENOISE_CHROMA_AT_FULL = 2.0


@dataclass(frozen=True)
class DetailEnhance:
    sharpen: int = 0
    denoise: int = 0

    @property
    def is_neutral(self) -> bool:
        return self.sharpen == 0 and self.denoise == 0

    def as_dict(self) -> dict[str, int]:
        return {"sharpen": self.sharpen, "denoise": self.denoise}


def detail_preview_model() -> dict[str, float]:
    return {
        "sharpenAmountAtFull": SHARPEN_AMOUNT_AT_FULL,
        "denoiseLumaAtFull": DENOISE_LUMA_AT_FULL,
        "denoiseChromaAtFull": DENOISE_CHROMA_AT_FULL,
    }


def _round_half_away_from_zero(value: float) -> int:
    if value >= 0:
        return int(value + 0.5)
    return int(value - 0.5)


def _parse_slider(value: object, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number from 0 to 100")
    number = float(value)
    if not math.isfinite(number) or number < SLIDER_MIN or number > SLIDER_MAX:
        raise ValueError(f"{key} must be a number from 0 to 100")
    return _round_half_away_from_zero(number)


def _read_slider(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    number = float(value)
    if not math.isfinite(number) or number < SLIDER_MIN or number > SLIDER_MAX:
        return 0
    return _round_half_away_from_zero(number)


def detail_from_effect_settings(raw: str | None) -> DetailEnhance:
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return DetailEnhance()
    if not isinstance(parsed, dict):
        return DetailEnhance()
    nested = parsed.get(DETAIL_KEY)
    source = nested if isinstance(nested, dict) else {}
    return DetailEnhance(
        sharpen=_read_slider(source.get("sharpen")),
        denoise=_read_slider(source.get("denoise")),
    )


def parse_detail_payload(payload: Mapping[str, object]) -> DetailEnhance:
    if not any(key in payload for key in ("sharpen", "denoise")):
        raise ValueError("JSON body must include sharpen or denoise")
    sharpen = (
        _parse_slider(payload["sharpen"], "sharpen") if "sharpen" in payload else 0
    )
    denoise = (
        _parse_slider(payload["denoise"], "denoise") if "denoise" in payload else 0
    )
    if "sharpen" in payload and "denoise" not in payload:
        # Partial patch handled by caller merging with current.
        pass
    return DetailEnhance(sharpen=sharpen, denoise=denoise)


def parse_detail_patch(
    payload: Mapping[str, object], current: DetailEnhance
) -> DetailEnhance:
    if not any(key in payload for key in ("sharpen", "denoise")):
        raise ValueError("JSON body must include sharpen or denoise")
    sharpen = current.sharpen
    denoise = current.denoise
    if "sharpen" in payload:
        sharpen = _parse_slider(payload["sharpen"], "sharpen")
    if "denoise" in payload:
        denoise = _parse_slider(payload["denoise"], "denoise")
    return DetailEnhance(sharpen=sharpen, denoise=denoise)


def dump_detail(existing: str | None, detail: DetailEnhance) -> str:
    try:
        parsed = json.loads(existing) if existing else {}
    except json.JSONDecodeError:
        parsed = {}
    data = parsed if isinstance(parsed, dict) else {}
    data[DETAIL_KEY] = detail.as_dict()
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def _fmt(value: float) -> str:
    return f"{value:.4f}"


def ffmpeg_detail_chain(detail: DetailEnhance) -> str:
    """``unsharp`` then ``hqdn3d``, or empty when both are off."""
    if detail.is_neutral:
        return ""
    parts: list[str] = []
    if detail.sharpen > 0:
        amount = (detail.sharpen / 100.0) * SHARPEN_AMOUNT_AT_FULL
        parts.append(f"unsharp=5:5:{_fmt(amount)}:5:5:0.0000")
    if detail.denoise > 0:
        luma = (detail.denoise / 100.0) * DENOISE_LUMA_AT_FULL
        chroma = (detail.denoise / 100.0) * DENOISE_CHROMA_AT_FULL
        parts.append(
            f"hqdn3d={_fmt(luma)}:{_fmt(chroma)}:{_fmt(luma * 0.5)}:{_fmt(chroma * 0.5)}"
        )
    return ",".join(parts)
