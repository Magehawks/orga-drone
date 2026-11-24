"""Independent scope reference vectors (#364/#366).

Proves incorrect histogram bins, missing vectorscope targets, legal-range
mishandling, and non-deterministic subsample counts fail CI.
"""

from __future__ import annotations

import pytest

from tests.scopes_reference import (
    ScopeFrameRef,
    accumulate_histogram,
    accumulate_rgb_parade,
    accumulate_vectorscope,
    accumulate_waveform,
    color_bar_frame,
    color_bar_vectorscope_targets,
    expand_legal_range,
    histogram_bin,
    luma_y,
    solid_frame,
    vectorscope_cb_cr,
)


def test_histogram_exact_bins_for_solid_gray() -> None:
    frame = solid_frame(8, 4, (0.5, 0.5, 0.5))
    hist = accumulate_histogram(frame)
    assert hist["bins"] == 256
    assert histogram_bin(0.5) == 128
    assert hist["absolute"]["r"][128] == pytest.approx(hist["weight_sum"])
    assert hist["absolute"]["r"][0] == 0.0
    assert hist["absolute"]["r"][255] == 0.0
    assert hist["sample_count"] == 32


def test_wrong_bin_assignment_is_detectable() -> None:
    frame = solid_frame(4, 4, (1.0, 0.0, 0.0))
    hist = accumulate_histogram(frame)
    with pytest.raises(AssertionError):
        assert hist["absolute"]["r"][0] == pytest.approx(hist["weight_sum"])


def test_black_and_channel_isolation() -> None:
    black = accumulate_histogram(solid_frame(2, 2, (0.0, 0.0, 0.0)))
    assert black["absolute"]["luma"][0] == pytest.approx(black["weight_sum"])
    red = accumulate_histogram(solid_frame(2, 2, (1.0, 0.0, 0.0)))
    assert red["absolute"]["r"][255] == pytest.approx(red["weight_sum"])
    assert red["absolute"]["g"][0] == pytest.approx(red["weight_sum"])


def test_waveform_and_parade_coordinates() -> None:
    gray = accumulate_waveform(solid_frame(16, 8, (0.5, 0.5, 0.5)), columns=32, rows=32)
    mid = int(0.5 * 32)
    mass = sum(gray["density"][mid * 32 + c] for c in range(32))
    assert mass > 0
    assert gray["axis"]["y"] == "Y_prime_bt709"
    parade = accumulate_rgb_parade(solid_frame(8, 4, (0.0, 1.0, 0.0)), columns=16, rows=16)
    g_mass = sum(parade["panels"]["g"][15 * 16 + c] for c in range(16))
    r_mass = sum(parade["panels"]["r"][0 * 16 + c] for c in range(16))
    assert g_mass > 0
    assert r_mass > 0
    assert parade["channels"] == ["R_prime", "G_prime", "B_prime"]


def test_bt709_vectorscope_reference_coords() -> None:
    cb, cr, y = vectorscope_cb_cr(1.0, 0.0, 0.0)
    assert cb == pytest.approx((0.0 - luma_y(1.0, 0.0, 0.0)) / 1.8556)
    assert cr == pytest.approx((1.0 - luma_y(1.0, 0.0, 0.0)) / 1.5748)
    assert y == pytest.approx(luma_y(1.0, 0.0, 0.0))
    scope = accumulate_vectorscope(color_bar_frame(), size=64)
    assert scope["axis"]["encoding"] == "bt709_encoded_opponent"
    assert scope["axis"]["range"] == [-0.5, 0.5]
    for target in color_bar_vectorscope_targets():
        col = min(63, max(0, int((target["cb"] + 0.5) * 64)))
        row = min(63, max(0, int((0.5 - target["cr"]) * 64)))
        assert scope["density"][row * 64 + col] > 0


def test_alpha_weighting_and_zero_alpha_ignored() -> None:
    rgba = [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.5,
    ]
    frame = ScopeFrameRef(width=2, height=1, rgba=rgba)
    hist = accumulate_histogram(frame)
    assert hist["weight_sum"] == pytest.approx(0.5)
    assert hist["absolute"]["g"][255] == pytest.approx(0.5)
    assert hist["absolute"]["r"][255] == 0.0


def test_legal_range_expanded_exactly_once() -> None:
    assert expand_legal_range(16 / 255) == pytest.approx(0.0)
    assert expand_legal_range(235 / 255) == pytest.approx(1.0)
    limited = solid_frame(2, 2, (16 / 255, 16 / 255, 16 / 255), legal_range=True)
    hist = accumulate_histogram(limited)
    assert hist["absolute"]["luma"][0] == pytest.approx(hist["weight_sum"])
    raw = solid_frame(2, 2, (16 / 255, 16 / 255, 16 / 255), legal_range=False)
    raw_hist = accumulate_histogram(raw)
    assert raw_hist["absolute"]["luma"][0] == 0.0


def test_deterministic_subsampling_sample_count() -> None:
    full = accumulate_histogram(solid_frame(40, 20, (0.25, 0.25, 0.25), sample_factor=1))
    stepped = accumulate_histogram(solid_frame(40, 20, (0.25, 0.25, 0.25), sample_factor=4))
    assert full["sample_count"] == 800
    assert stepped["sample_count"] == 50
    assert stepped["sample_factor"] == 4
    assert stepped["absolute"]["r"][histogram_bin(0.25)] == pytest.approx(stepped["weight_sum"])