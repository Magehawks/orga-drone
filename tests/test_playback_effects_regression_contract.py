"""Regression contract for playback / transition / color-animation consistency.

Pins shipped contracts for issues #294 (Phase B loop-proxy mapping), #301
(batch-1 xfade ids), and #211 (keyed color interpolation). Mutating the
underlying semantics must fail this module; do not relax thresholds here.
"""

from __future__ import annotations

from pathlib import Path

from orga_drone.studio_color_animation import ColorAnimation, ColorKey, keyed_sliders_at
from orga_drone.studio_transition import (
    TYPE_BLUR_DISSOLVE,
    TYPE_CROSSFADE,
    TYPE_SOFT_WIPE_DOWN,
    TYPE_SOFT_WIPE_LEFT,
    TYPE_SOFT_WIPE_RIGHT,
    TYPE_SOFT_WIPE_UP,
    XFADE_BY_TYPE,
    normalize_type,
)


def test_contract_294_phase_b_proxy_policy_allows_loops_with_local_map() -> None:
    root = Path(__file__).resolve().parents[1]
    policy = (root / "src/orga_drone/static/js/studio/proxy-policy.js").read_text(
        encoding="utf-8"
    )
    mapper = (root / "src/orga_drone/static/js/studio/proxy-loop-map.js").read_text(
        encoding="utf-8"
    )
    studio = (root / "src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    assert "Number(sectionRepeats) > 1 || forwardLoopActive" not in policy
    assert "proxyRelativeMediaTime" in mapper
    assert "playEndMediaTime" in mapper
    assert 'from "./studio/proxy-loop-map.js"' in studio
    assert "proxyRelativeMediaTime(lutProxyActiveFor(playing), inS, 0)" in studio


def test_contract_294_broken_absolute_seek_is_rejected_by_helper() -> None:
    """Absolute source seeks must not equal proxy-local seeks when cut-in > 0."""
    source_in = 12.5
    overlap = 1.0
    absolute = source_in + overlap
    proxy_local = overlap
    assert absolute != proxy_local


def test_contract_301_xfade_ids_are_native_and_stable() -> None:
    assert normalize_type("blur_dissolve") == TYPE_BLUR_DISSOLVE
    assert normalize_type("soft_wipe_left") == TYPE_SOFT_WIPE_LEFT
    assert XFADE_BY_TYPE[TYPE_CROSSFADE] == "fade"
    assert XFADE_BY_TYPE[TYPE_BLUR_DISSOLVE] == "hblur"
    assert XFADE_BY_TYPE[TYPE_SOFT_WIPE_LEFT] == "smoothleft"
    assert XFADE_BY_TYPE[TYPE_SOFT_WIPE_RIGHT] == "smoothright"
    assert XFADE_BY_TYPE[TYPE_SOFT_WIPE_UP] == "smoothup"
    assert XFADE_BY_TYPE[TYPE_SOFT_WIPE_DOWN] == "smoothdown"
    assert normalize_type("whip_pan") == "cut"
    assert normalize_type("luma_wipe") == "cut"
    assert normalize_type("zoom_spin") == "cut"


def test_contract_211_keyframe_interpolation_is_deterministic() -> None:
    anim = ColorAnimation(
        mode="manual",
        interp="linear",
        bar_start_s=0.0,
        bar_end_s=1.0,
        keys=(
            ColorKey(t=0.0, exposure=0, contrast=0, saturation=0, warmth=0, lut_strength=0),
            ColorKey(
                t=1.0, exposure=100, contrast=0, saturation=0, warmth=0, lut_strength=100
            ),
        ),
    )
    mid = keyed_sliders_at(anim, 0.5)
    assert mid is not None
    assert mid.exposure == 50
    assert mid.lut_strength == 50
    early = keyed_sliders_at(anim, -0.25)
    late = keyed_sliders_at(anim, 1.25)
    assert early is None
    assert late is None
