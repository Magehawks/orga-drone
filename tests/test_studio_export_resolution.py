"""Unit tests for Studio export resolution and destination helpers (Issue #17)."""

from __future__ import annotations

from pathlib import Path

import pytest

from orga_drone.app_prefs import get_last_export_directory, set_last_export_directory
from orga_drone.studio_export_resolution import (
    available_export_resolutions,
    classify_source_height,
    default_export_height,
    default_videos_directory,
    export_resolution_filename_tag,
    max_project_export_height,
    resolve_export_directory,
    suggested_export_filename,
)


@pytest.mark.parametrize(
    ("height", "expected"),
    [
        (720, 720),
        (1080, 1080),
        (1440, 1440),
        (2160, 2160),
        (3840, 2160),  # width mistaken? still classifies by height
        (800, 720),
        (900, 720),
        (1200, 1080),
        (1500, 1440),
        (2000, 1440),
        (2110, 2160),
        (480, None),
        (None, None),
        (0, None),
    ],
)
def test_classify_source_height(height: int | None, expected: int | None) -> None:
    assert classify_source_height(height) == expected


def test_available_resolutions_720_only() -> None:
    opts = available_export_resolutions([720])
    assert [o.height for o in opts] == [720]
    assert default_export_height([720]) == 720
    assert all(not o.recommended for o in opts)


def test_available_resolutions_1080() -> None:
    opts = available_export_resolutions([1080])
    assert [o.height for o in opts] == [720, 1080]
    assert default_export_height([1080]) == 1080
    assert any(o.recommended and o.height == 1080 for o in opts)


def test_available_resolutions_1440() -> None:
    opts = available_export_resolutions([1440])
    assert [o.height for o in opts] == [720, 1080, 1440]
    assert default_export_height([1440]) == 1080


def test_available_resolutions_4k() -> None:
    opts = available_export_resolutions([2160])
    assert [o.height for o in opts] == [720, 1080, 1440, 2160]
    assert default_export_height([2160]) == 1080
    assert not any(o.height == 2160 and o.recommended for o in opts)


def test_mixed_resolutions_use_max() -> None:
    heights = [720, 1080, 2160, None]
    assert max_project_export_height(heights) == 2160
    opts = available_export_resolutions(heights)
    assert [o.height for o in opts] == [720, 1080, 1440, 2160]
    assert default_export_height(heights) == 1080


def test_no_usable_video_resolution() -> None:
    assert available_export_resolutions([]) == []
    assert available_export_resolutions([None, 480]) == []
    assert default_export_height([None]) is None


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Summer Alps 2026", "Summer Alps 2026.mp4"),
        ("a/b\\c:d*e?", "a b c d e.mp4"),
        ("", "Your story.mp4"),
        ("   ", "Your story.mp4"),
        ("CON", "export-CON.mp4"),
        ("My.Story.", "My.Story.mp4"),
    ],
)
def test_suggested_export_filename(title: str, expected: str) -> None:
    assert suggested_export_filename(title) == expected


@pytest.mark.parametrize(
    ("height", "tag"),
    [
        (1080, "1080p"),
        (2160, "4k"),
        (720, "720p"),
        (1440, "2560x1440"),
        (480, "853x480"),
    ],
)
def test_export_resolution_filename_tag(height: int, tag: str) -> None:
    assert export_resolution_filename_tag(height) == tag


@pytest.mark.parametrize(
    ("title", "height", "expected"),
    [
        ("Summer Alps 2026", 1080, "Summer Alps 2026_1080p.mp4"),
        ("Summer Alps 2026", 2160, "Summer Alps 2026_4k.mp4"),
        ("Summer Alps 2026", 720, "Summer Alps 2026_720p.mp4"),
        ("Summer Alps 2026", 1440, "Summer Alps 2026_2560x1440.mp4"),
        ("a/b\\c:d*e?", 1080, "a b c d e_1080p.mp4"),
        ("", 2160, "Your story_4k.mp4"),
        ("   ", 720, "Your story_720p.mp4"),
        ("CON", 1440, "export-CON_2560x1440.mp4"),
        ("My.Story.", 1080, "My.Story_1080p.mp4"),
    ],
)
def test_suggested_export_filename_includes_resolution(
    title: str, height: int, expected: str
) -> None:
    assert suggested_export_filename(title, height=height) == expected


def test_resolve_export_directory_prefers_last(tmp_path: Path) -> None:
    last = tmp_path / "exports"
    last.mkdir()
    resolved = resolve_export_directory(str(last))
    assert resolved == last.resolve()
    missing = resolve_export_directory(str(tmp_path / "gone"))
    assert missing == default_videos_directory()


def test_last_export_directory_prefs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orga_drone.config import Settings
    import orga_drone.app_prefs as prefs

    monkeypatch.setattr(prefs, "settings", Settings(data_dir=tmp_path / "data"))
    assert get_last_export_directory() is None
    target = tmp_path / "out"
    target.mkdir()
    set_last_export_directory(target)
    assert get_last_export_directory() == str(target)
