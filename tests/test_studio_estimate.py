"""Unit tests for Studio runtime estimate helpers."""

from __future__ import annotations

from dataclasses import dataclass

from orga_drone.studio_estimate import (
    DEFAULT_PHOTO_DURATION_S,
    effective_kind,
    effective_seconds,
    format_studio_duration,
    resolve_project_time,
    summarize_studio_items,
)


@dataclass
class _Item:
    available: bool
    kind: str | None
    photo_duration_s: float | None = None
    duration_s: float | None = None


def test_effective_kind_live_wins() -> None:
    assert (
        effective_kind(available=True, live_kind="video", kind_snapshot="photo")
        == "video"
    )
    assert (
        effective_kind(available=False, live_kind="video", kind_snapshot="photo")
        == "photo"
    )
    assert (
        effective_kind(available=False, live_kind=None, kind_snapshot=None) == "unknown"
    )


def test_effective_seconds_rules() -> None:
    assert (
        effective_seconds(
            kind="photo", photo_duration_s=None, duration_s=None, available=True
        )
        == DEFAULT_PHOTO_DURATION_S
    )
    assert (
        effective_seconds(
            kind="photo", photo_duration_s=4.5, duration_s=None, available=False
        )
        == 4.5
    )
    assert (
        effective_seconds(
            kind="video", photo_duration_s=None, duration_s=12.0, available=True
        )
        == 12.0
    )
    assert (
        effective_seconds(
            kind="video", photo_duration_s=None, duration_s=None, available=True
        )
        is None
    )
    assert (
        effective_seconds(
            kind="video", photo_duration_s=None, duration_s=12.0, available=False
        )
        is None
    )
    assert (
        effective_seconds(
            kind="unknown", photo_duration_s=3.0, duration_s=9.0, available=True
        )
        is None
    )


def test_summarize_and_hhmmss() -> None:
    items = [
        _Item(available=True, kind="photo", photo_duration_s=None),
        _Item(available=True, kind="photo", photo_duration_s=5.0),
        _Item(available=True, kind="video", duration_s=62.0),
        _Item(available=True, kind="video", duration_s=None),
        _Item(available=False, kind="video", duration_s=40.0),
        _Item(available=False, kind="photo", photo_duration_s=2.0),
    ]
    summary = summarize_studio_items(items)
    assert summary.photo_count == 3
    assert summary.video_count == 3
    # 3 + 5 + 62 + 2 = 72 (missing/unavailable videos excluded)
    assert summary.estimated_total_s == 72.0
    assert summary.estimated_total_label == "00:01:12"
    assert format_studio_duration(107.5) == "00:01:48"
    assert format_studio_duration(0) == "00:00:00"


def test_resolve_project_time_maps_clips() -> None:
    assert resolve_project_time([], 0) is None
    assert resolve_project_time([0, -1], 1) is None

    hit = resolve_project_time([3.0, 10.0, 5.0], 0.0)
    assert hit is not None
    assert hit.index == 0 and hit.start_s == 0.0 and hit.local_s == 0.0
    assert hit.at_end is False

    hit = resolve_project_time([3.0, 10.0, 5.0], 3.0)
    assert hit is not None
    assert hit.index == 1 and hit.start_s == 3.0 and abs(hit.local_s - 0.0) < 1e-9

    hit = resolve_project_time([3.0, 10.0, 5.0], 8.5)
    assert hit is not None
    assert hit.index == 1 and abs(hit.local_s - 5.5) < 1e-9

    hit = resolve_project_time([3.0, 10.0, 5.0], 18.0)
    assert hit is not None
    assert hit.index == 2 and hit.at_end is True and hit.local_s == 5.0

    # Zero-duration spans are skipped; indices refer to original list positions.
    hit = resolve_project_time([0.0, 4.0, 0.0, 6.0], 4.0)
    assert hit is not None
    assert hit.index == 3 and hit.start_s == 4.0 and hit.local_s == 0.0

