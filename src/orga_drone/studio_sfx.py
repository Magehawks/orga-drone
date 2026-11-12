"""Pure helpers for the Studio SFX lane (ADR 0036 / issue #184)."""

from __future__ import annotations

import math

STUDIO_SFX_LANE = "sfx"
STUDIO_SFX_MAX_CLIPS = 16
STUDIO_SFX_START_MAX_S = 86400.0
STUDIO_SFX_FADE_MAX_S = 10.0


def _finite(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def clamp_sfx_volume(value: object) -> float:
    return max(0.0, min(1.0, _finite(value, label="volume")))


def clamp_sfx_fade_s(value: object) -> float:
    return max(0.0, min(STUDIO_SFX_FADE_MAX_S, _finite(value, label="fade")))


def clamp_sfx_start_s(value: object) -> float:
    start = _finite(value, label="start_s")
    if start < 0:
        raise ValueError("start_s must be >= 0")
    if start > STUDIO_SFX_START_MAX_S:
        raise ValueError("start_s is too large")
    return start


def resolve_sfx_trim(
    *,
    duration_s: float | None,
    source_in_s: object | None,
    source_out_s: object | None,
) -> tuple[float, float]:
    """Return absolute source in/out for one SFX clip.

    Missing bounds default to the full probed file. Out must be greater than in.
    """
    media = (
        _finite(duration_s, label="duration_s")
        if duration_s is not None
        else None
    )
    if media is not None and media <= 0:
        raise ValueError("SFX duration must be greater than zero")
    start = 0.0 if source_in_s is None else _finite(source_in_s, label="source_in_s")
    if start < 0:
        raise ValueError("source_in_s must be >= 0")
    if media is not None:
        end = media if source_out_s is None else _finite(source_out_s, label="source_out_s")
        end = min(end, media)
        start = min(start, media)
    else:
        if source_out_s is None:
            raise ValueError("source_out_s is required when duration is unknown")
        end = _finite(source_out_s, label="source_out_s")
    if end - start <= 1e-6:
        raise ValueError("SFX trim range must be greater than zero")
    return start, end


def sfx_audible_duration_s(
    *,
    duration_s: float | None,
    source_in_s: float | None,
    source_out_s: float | None,
) -> float:
    start, end = resolve_sfx_trim(
        duration_s=duration_s,
        source_in_s=source_in_s,
        source_out_s=source_out_s,
    )
    return end - start
