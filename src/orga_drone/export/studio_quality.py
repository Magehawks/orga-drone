"""Studio export quality presets (Issue #149).

These are encode targets, not a promise of lossless output or a particular file size.
Share-preset video exports stay on Standard, which matches the previous implicit
x264 default (CRF 23, veryfast).
"""

from __future__ import annotations

DEFAULT_EXPORT_QUALITY = "high"
SHARE_EXPORT_QUALITY = "standard"

_SPECS: dict[str, tuple[int, str]] = {
    "standard": (23, "veryfast"),
    "high": (20, "veryfast"),
    "best": (17, "slow"),
}


def export_quality_ids() -> tuple[str, ...]:
    return tuple(_SPECS)


def coerce_export_quality(
    value: object | None,
    *,
    default: str = DEFAULT_EXPORT_QUALITY,
) -> str:
    """Return a known quality id.

    ``None`` and a blank string use ``default``. Anything else unknown raises
    ``ValueError``.
    """
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, str):
        raise ValueError("Choose an export quality.")
    key = value.strip().lower()
    if not key:
        return default
    if key not in _SPECS:
        raise ValueError("Choose an export quality.")
    return key


def x264_preset_and_crf(quality: str) -> tuple[str, str]:
    crf, preset = _SPECS[coerce_export_quality(quality, default=quality)]
    return preset, str(crf)
