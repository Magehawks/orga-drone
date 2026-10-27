"""Effekt lane ranges stay inside one bar, and 1× clip audio is not dropped."""

from __future__ import annotations

from pathlib import Path

from orga_drone.studio_effect_lane import (
    clear_slow,
    clear_zoom,
    mask_covers,
    preview_audio_source,
    speed_at,
    write_slow_bar,
    write_zoom_bar,
    zoom_factor_at,
)
from orga_drone.studio_frame import FrameTransform, dump_frame, ffmpeg_zoom_window
from orga_drone.studio_mask import Mask, MaskWindow, ffmpeg_mask_graph


def _zoomed() -> str:
    return dump_frame(
        None,
        FrameTransform(zoom_start=2.0, zoom_end=2.0),
    )


def test_zoom_bar_applies_only_inside_its_range() -> None:
    raw = write_zoom_bar(_zoomed(), 1.0, 3.0)
    assert zoom_factor_at(raw, 0.2, 8.0) == 1.0
    assert zoom_factor_at(raw, 2.0, 8.0) == 2.0
    graph = ffmpeg_zoom_window(
        FrameTransform(zoom_start=2.0, zoom_end=2.0),
        1.0,
        3.0,
        source_width=1920,
        source_height=1080,
    )
    assert "between" in graph
    cleared = clear_zoom(raw)
    assert zoom_factor_at(cleared, 2.0, 8.0) == 1.0


def test_mask_bar_does_not_cover_the_clip_outside_its_range() -> None:
    blur = Mask(
        id="blur1",
        effect="blur",
        strength=40,
        x=0.1,
        y=0.1,
        w=0.3,
        h=0.3,
        start_s=1.0,
        end_s=2.0,
    )
    pixel = Mask(
        id="pix1",
        effect="pixelate",
        strength=40,
        x=0.4,
        y=0.4,
        w=0.2,
        h=0.2,
        start_s=1.0,
        end_s=2.0,
    )
    assert mask_covers(blur, 0.2, 8.0) is False
    assert mask_covers(blur, 1.4, 8.0) is True
    assert mask_covers(pixel, 3.0, 8.0) is False
    assert mask_covers(pixel, 1.5, 8.0) is True
    graph = ffmpeg_mask_graph(
        base_chain="null",
        fades=[],
        windows=(
            MaskWindow(
                effect="pixelate",
                x=10,
                y=10,
                w=80,
                h=80,
                radius=4,
                block=8,
                start_s=1.0,
                end_s=2.0,
            ),
        ),
        include_tail=False,
    )
    assert "enable=" in graph
    assert "flags=neighbor" in graph


def test_slow_bar_is_half_or_quarter_only_inside_its_range() -> None:
    half = write_slow_bar(None, 1.0, 3.0, 0.5)
    assert speed_at(half, 0.2, 8.0, 1.0) == 1.0
    assert speed_at(half, 2.0, 8.0, 1.0) == 0.5
    quarter = write_slow_bar(None, 1.0, 3.0, 0.25)
    assert speed_at(quarter, 2.0, 8.0, 1.0) == 0.25
    assert speed_at(quarter, 4.0, 8.0, 1.0) == 1.0
    cleared = clear_slow(quarter)
    assert speed_at(cleared, 2.0, 8.0, 1.0) == 1.0


def test_removing_a_bar_clears_that_effect() -> None:
    zoom = write_zoom_bar(_zoomed(), 0.0, 4.0)
    assert zoom_factor_at(clear_zoom(zoom), 1.0, 4.0) == 1.0
    slow = write_slow_bar(None, 0.0, 4.0, 0.5)
    assert speed_at(clear_slow(slow), 1.0, 4.0, 1.0) == 1.0
    gone = Mask(
        id="gone",
        effect="blur",
        strength=10,
        x=0.1,
        y=0.1,
        w=0.2,
        h=0.2,
    )
    assert mask_covers(gone, 1.0, 4.0) is True


def test_normal_speed_preview_uses_the_original_audio() -> None:
    assert (
        preview_audio_source(
            has_proxy=True,
            stream_url="/media/9/stream",
            playback_speed=1.0,
        )
        == "/media/9/stream"
    )
    assert (
        preview_audio_source(
            has_proxy=True,
            stream_url="/media/9/stream",
            playback_speed=0.5,
        )
        == ""
    )
    script = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    page = Path("src/orga_drone/templates/studio.html").read_text(encoding="utf-8")
    assert "function syncClipAudio" in script
    assert 'dataset.hasProxy === "1"' in script
    assert "id=\"studio-effect-lane\"" in page
    encoder = Path("src/orga_drone/export/studio_encoder.py").read_text(encoding="utf-8")
    assert '"-map", "0:a:0"' in encoder or "'-map', '0:a:0'" in encoder
