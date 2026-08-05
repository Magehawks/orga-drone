"""Unit tests for Studio video cut / source-range split helpers."""

from __future__ import annotations

import pytest

from orga_drone.studio_cut import (
    MIN_SEGMENT_S,
    SourceRange,
    resolve_source_range,
    split_source_range,
)
from orga_drone.studio_estimate import effective_seconds


def test_resolve_full_media_when_offsets_null() -> None:
    rang = resolve_source_range(
        source_in_s=None, source_out_s=None, media_duration_s=12.0
    )
    assert rang == SourceRange(0.0, 12.0)
    assert rang.duration_s == 12.0


def test_resolve_trimmed_offsets() -> None:
    rang = resolve_source_range(
        source_in_s=2.0, source_out_s=8.5, media_duration_s=12.0
    )
    assert rang == SourceRange(2.0, 8.5)
    assert rang.duration_s == 6.5


def test_resolve_clamps_out_to_media_duration() -> None:
    rang = resolve_source_range(
        source_in_s=1.0, source_out_s=99.0, media_duration_s=10.0
    )
    assert rang == SourceRange(1.0, 10.0)


def test_resolve_rejects_empty_or_inverted() -> None:
    assert (
        resolve_source_range(source_in_s=5.0, source_out_s=5.0, media_duration_s=10.0)
        is None
    )
    assert (
        resolve_source_range(source_in_s=8.0, source_out_s=3.0, media_duration_s=10.0)
        is None
    )
    assert (
        resolve_source_range(source_in_s=None, source_out_s=None, media_duration_s=0)
        is None
    )
    assert (
        resolve_source_range(source_in_s=None, source_out_s=None, media_duration_s=None)
        is None
    )


def test_split_preserves_total_duration() -> None:
    rang = SourceRange(1.0, 11.0)
    left, right = split_source_range(rang, 4.0)
    assert left == SourceRange(1.0, 5.0)
    assert right == SourceRange(5.0, 11.0)
    assert left.duration_s + right.duration_s == pytest.approx(rang.duration_s)


def test_split_rejects_ends_and_outside() -> None:
    rang = SourceRange(0.0, 10.0)
    with pytest.raises(ValueError):
        split_source_range(rang, 0.0)
    with pytest.raises(ValueError):
        split_source_range(rang, 10.0)
    with pytest.raises(ValueError):
        split_source_range(rang, MIN_SEGMENT_S)
    with pytest.raises(ValueError):
        split_source_range(rang, 10.0 - MIN_SEGMENT_S)
    with pytest.raises(ValueError):
        split_source_range(rang, -1.0)
    with pytest.raises(ValueError):
        split_source_range(rang, 11.0)


def test_split_near_middle_ok() -> None:
    rang = SourceRange(0.0, 10.0)
    left, right = split_source_range(rang, 0.06)
    assert left.duration_s == pytest.approx(0.06)
    assert right.duration_s == pytest.approx(9.94)


def test_effective_seconds_uses_source_offsets() -> None:
    assert (
        effective_seconds(
            kind="video",
            photo_duration_s=None,
            duration_s=20.0,
            available=True,
            source_in_s=2.0,
            source_out_s=8.0,
        )
        == 6.0
    )
    assert (
        effective_seconds(
            kind="video",
            photo_duration_s=None,
            duration_s=20.0,
            available=True,
        )
        == 20.0
    )
