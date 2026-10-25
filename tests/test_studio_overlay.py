"""Clip overlays: timing, persistence, and export graph (Issue #78, slice A)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.export.studio_config import StudioExportClip
from orga_drone.export.studio_encoder import (
    _segment_filter_invocation,
    _segment_vf,
    _segment_vf_for_clip,
    build_stitch_filters,
)
from orga_drone.ffmpeg_bin import find_ffmpeg
from orga_drone.studio_export import _clip_to_export_clip
from orga_drone.studio_image import image_adjust_from_effect_settings
from orga_drone.studio_overlay import (
    Overlay,
    OverlayAssetMissing,
    content_rect,
    dump_overlays,
    ffmpeg_overlay_graph,
    filter_time_origin,
    overlay_box_pixels,
    overlay_is_active,
    overlays_from_effect_settings,
    parse_overlays,
    render_overlay_png,
    split_overlay_settings,
    store_overlay_asset,
)


def _seed_media(
    db: Database,
    root_path: Path,
    *,
    filename: str,
    kind: str,
    duration_s: float | None,
) -> int:
    root_path.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root_path, label="test")
    media_file = root_path / filename
    media_file.write_bytes(b"media")
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": kind,
            "filename": filename,
            "path": str(media_file.resolve()),
            "size_bytes": 5,
            "duration_s": duration_s,
            "recorded_at": "2024-01-02T10:00:00",
            "sequence": 1,
            "mode": None,
            "drone_model": "Avata 2",
            "camera_model": None,
            "latitude": None,
            "longitude": None,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )


def _add(db: Database, media_id: int) -> int:
    item = db.get_media(media_id)
    assert item is not None
    clip_id, _created = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
    )
    return clip_id


def _text(text: str = "Landmark", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "ovtext0001",
        "kind": "text",
        "start_s": 1,
        "end_s": 3,
        "x": 0.1,
        "y": 0.2,
        "w": 0.4,
        "h": 0.16,
        "rotation": 0,
        "text": text,
        "font_size": 0.06,
        "color": "#ffffff",
        "fill": "#00000000",
        "stroke": "#ffffff",
        "stroke_width": 0.012,
        "asset_name": "",
    }
    payload.update(overrides)
    return payload


def test_parse_clamps_time_and_rejects_injection() -> None:
    overlays, clamped = parse_overlays([_text(start_s=0, end_s=99)], duration_s=4)
    assert clamped is True
    assert overlays[0].end_s == 4.0
    with pytest.raises(ValueError, match="hex color"):
        parse_overlays([_text(color="red;drawtext=text=owned")], duration_s=4)
    with pytest.raises(ValueError, match="invalid"):
        parse_overlays([_text(kind="drawtext")], duration_s=4)
    with pytest.raises(ValueError, match="number"):
        parse_overlays([_text(x=True)], duration_s=4)
    hostile = _text(text="between(t,0,1),drawtext=text=evil")
    parsed, _changed = parse_overlays([hostile], duration_s=4)
    graph = ffmpeg_overlay_graph(
        base_chain="scale=1280:720",
        fades=[],
        windows=[(parsed[0].start_s, parsed[0].end_s)],
        first_input=1,
    )
    assert "drawtext" not in graph
    assert "evil" not in graph
    assert "between(t\\,1.0000\\,3.0000)" in graph


def test_two_overlays_and_letterbox_box() -> None:
    first = _text(id="ovtext0001", text="A", x=0.1, y=0.1)
    second = _text(id="ovarrow001", kind="arrow", text="", x=0.5, y=0.4, w=0.3, h=0.12)
    overlays, _clamped = parse_overlays([first, second], duration_s=8)
    assert len(overlays) == 2
    assert overlays[0].text == "A"
    assert overlays[1].kind == "arrow"
    portrait = content_rect(1920, 1080, 1080, 1920)
    origin_x, origin_y, content_w, content_h = portrait
    assert origin_x > 0
    assert origin_y == 0
    assert content_h == 1080
    assert content_w < 1920
    landscape = content_rect(1920, 1080, 1920, 1080)
    assert landscape == (0, 0, 1920, 1080)
    box = overlay_box_pixels(overlays[0], portrait)
    assert box[0] >= origin_x
    assert box[1] >= origin_y
    assert overlay_is_active(overlays[0], 1.0, duration_s=8)
    assert overlay_is_active(overlays[0], 3.0, duration_s=8) is True
    assert overlay_is_active(overlays[0], 3.2, duration_s=8) is False


def test_split_overlay_settings_offsets_the_right_clip() -> None:
    blob = dump_overlays(
        "{}",
        (
            Overlay(
                id="ovtext0001",
                kind="text",
                start_s=4.0,
                end_s=8.0,
                x=0.1,
                y=0.2,
                w=0.4,
                h=0.16,
                text="Tower",
            ),
        ),
    )
    left_blob, right_blob = split_overlay_settings(blob, 5.0, left_s=5.0, right_s=3.0)
    left = overlays_from_effect_settings(left_blob, duration_s=5)
    right = overlays_from_effect_settings(right_blob, duration_s=3)
    assert left[0].start_s == pytest.approx(4.0)
    assert left[0].end_s == pytest.approx(5.0)
    assert right[0].start_s == pytest.approx(0.0)
    assert right[0].end_s == pytest.approx(3.0)


def test_video_filter_clock_starts_at_kept_in_point() -> None:
    assert filter_time_origin(kind="photo", source_start_s=2) == 0
    assert filter_time_origin(kind="video", source_start_s=4) == 0
    graph = ffmpeg_overlay_graph(
        base_chain="scale=320:180",
        fades=["fade=t=in:st=0:d=0.2000"],
        windows=[(4.0, 8.0)],
        first_input=1,
    )
    assert "between(t\\,4.0000\\,8.0000)" in graph
    assert graph.index("overlay=") < graph.index("fade=t=in")
    assert "[vout]" in graph


def test_neutral_segment_string_has_no_overlay() -> None:
    clip = StudioExportClip(source_path=Path("clip.mp4"), kind="video", duration_s=2)
    assert _segment_vf_for_clip(1280, 720, clip) == _segment_vf(1280, 720)
    left = StudioExportClip(
        source_path=Path("a.mp4"),
        kind="video",
        duration_s=2,
        transition_type="crossfade",
        transition_s=0.4,
        overlays=(
            Overlay(
                id="ovtext0001",
                kind="text",
                start_s=0,
                end_s=2,
                x=0.1,
                y=0.1,
                w=0.3,
                h=0.1,
                text="Hi",
            ),
        ),
    )
    right = StudioExportClip(source_path=Path("b.mp4"), kind="video", duration_s=2)
    stitch = ";".join(build_stitch_filters((left, right)))
    assert "xfade=" in stitch
    assert "overlay=" not in stitch


def test_render_shapes_and_missing_image(tmp_path: Path) -> None:
    arrow = Overlay(
        id="ovarrow001",
        kind="arrow",
        start_s=0,
        end_s=2,
        x=0.2,
        y=0.4,
        w=0.3,
        h=0.12,
    )
    dest = tmp_path / "arrow.png"
    render_overlay_png(
        arrow,
        frame_width=320,
        frame_height=180,
        source_width=1080,
        source_height=1920,
        asset_path=None,
        dest=dest,
    )
    with Image.open(dest) as image:
        assert image.mode == "RGBA"
        assert image.getpixel((0, 0))[3] == 0
        opaque = 0
        for y in range(image.height):
            for x in range(image.width):
                if image.getpixel((x, y))[3] > 0:
                    opaque += 1
        assert opaque > 10
    missing = Overlay(
        id="ovimage001",
        kind="image",
        start_s=0,
        end_s=1,
        x=0.1,
        y=0.1,
        w=0.2,
        h=0.2,
        asset_name="ab" * 16 + ".png",
    )
    with pytest.raises(OverlayAssetMissing):
        render_overlay_png(
            missing,
            frame_width=64,
            frame_height=64,
            source_width=64,
            source_height=64,
            asset_path=tmp_path / "gone.png",
            dest=tmp_path / "missing.png",
        )


def test_store_asset_rejects_non_images_and_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="PNG or JPEG"):
        store_overlay_asset(tmp_path, b"not an image")
    image = Image.new("RGB", (16, 16), (10, 20, 30))
    blob = tmp_path / "src.jpg"
    image.save(blob, "JPEG")
    name = store_overlay_asset(tmp_path, blob.read_bytes())
    assert name.endswith(".jpg")
    assert "/" not in name
    assert (tmp_path / "overlay-assets" / name).is_file()


def test_settings_persist_per_clip_and_survive_cut(tmp_path: Path) -> None:
    path = tmp_path / "studio.sqlite3"
    db = Database(path)
    media_id = _seed_media(db, tmp_path / "lib", filename="cloud.MP4", kind="video", duration_s=8.0)
    first = _add(db, media_id)
    second = _add(db, media_id)
    db.set_studio_image_adjust(first, {"exposure": 12})
    saved, clamped = db.set_studio_overlays(
        first,
        {"overlays": [_text(start_s=4, end_s=8, text="Tower"), _text(id="ovarrow001", kind="arrow", text="", x=0.5)]},
    )
    assert clamped is False
    assert len(overlays_from_effect_settings(saved.effect_settings, duration_s=8)) == 2
    assert image_adjust_from_effect_settings(saved.effect_settings).exposure == 12
    reopened = Database(path)
    kept = {item.id: item for item in reopened.list_studio_items()}[first]
    again = overlays_from_effect_settings(kept.effect_settings, duration_s=8)
    assert again[0].text == "Tower"
    assert again[1].kind == "arrow"
    other = {item.id: item for item in reopened.list_studio_items()}[second]
    assert overlays_from_effect_settings(other.effect_settings, duration_s=8) == ()
    exported = _clip_to_export_clip(reopened, kept)
    assert exported is not None
    assert exported.overlays[0].text == "Tower"
    assert exported.image.exposure == 12
    left, right = reopened.cut_studio_video_item(first, 5.0)
    left_ov = overlays_from_effect_settings(left.effect_settings, duration_s=5)
    right_ov = overlays_from_effect_settings(right.effect_settings, duration_s=3)
    assert left_ov[0].text == "Tower"
    assert left_ov[0].end_s == pytest.approx(5.0)
    assert right_ov[0].text == "Tower"
    assert right_ov[0].start_s == pytest.approx(0.0)
    assert right_ov[0].end_s == pytest.approx(3.0)
    card = reopened.add_studio_title_card(reopened.list_studio_projects()[0].id, title_text="Hi")
    with pytest.raises(ValueError, match="photos and videos"):
        reopened.set_studio_overlays(card.id, {"overlays": [_text()]})
    blob = dump_overlays(kept.effect_settings, ())
    assert "exposure" in blob
    assert json.loads(blob)["overlays"] == []


def test_cut_offsets_overlays_on_a_slowed_clip(tmp_path: Path) -> None:
    path = tmp_path / "studio.sqlite3"
    db = Database(path)
    media_id = _seed_media(db, tmp_path / "lib", filename="slow.MP4", kind="video", duration_s=8.0)
    clip_id = _add(db, media_id)
    db.set_studio_playback_speed(clip_id, 0.5)
    db.set_studio_overlays(
        clip_id,
        {"overlays": [_text(start_s=4, end_s=8, text="Tower")]},
    )
    left, right = db.cut_studio_video_item(clip_id, 3.0)
    left_ov = overlays_from_effect_settings(left.effect_settings, duration_s=6)
    right_ov = overlays_from_effect_settings(right.effect_settings, duration_s=10)
    assert left_ov[0].start_s == pytest.approx(4.0)
    assert left_ov[0].end_s == pytest.approx(6.0)
    assert right_ov[0].start_s == pytest.approx(0.0)
    assert right_ov[0].end_s == pytest.approx(2.0)


def test_segment_invocation_uses_vf_without_overlays(tmp_path: Path) -> None:
    clip = StudioExportClip(source_path=tmp_path / "clip.mp4", kind="video", duration_s=2)
    extra, filters = _segment_filter_invocation(clip, 320, 180, tmp_path)
    assert extra == []
    assert filters[0] == "-vf"
    assert "overlay=" not in filters[1]


def test_http_overlays_and_asset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    video_id = _add(
        db,
        _seed_media(db, tmp_path / "lib", filename="V.MP4", kind="video", duration_s=8.0),
    )
    client = TestClient(app)
    page = client.get("/studio")
    assert page.status_code == 200
    assert 'id="inspector-overlays" data-inspector-tab="overlays" hidden' in page.text
    assert "Einblendungen" in page.text or "Overlays" in page.text
    script = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    assert "overlayWrap.hidden = !(isPhoto || isVideo)" in script
    rejected = client.patch(f"/api/studio/{video_id}/overlays", json={"overlays": [_text(color="red")]})
    assert rejected.status_code == 400
    saved = client.patch(
        f"/api/studio/{video_id}/overlays",
        json={"overlays": [_text(text="Ridge", start_s=4, end_s=8), _text(id="ovcirc00001", kind="circle", text="")]},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["clamped"] is False
    assert len(body["overlays"]) == 2
    assert body["overlays"][0]["text"] == "Ridge"
    named = client.patch(
        f"/api/studio/{video_id}/overlays",
        json={"overlays": [_text(text="don't look")]},
    )
    assert named.status_code == 200
    again = client.get("/studio")
    assert "\\u0027" in again.text
    assert "data-overlays='" in again.text
    image = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
    blob = tmp_path / "mark.png"
    image.save(blob, "PNG")
    uploaded = client.post(
        "/api/studio/overlay-assets",
        files={"file": ("mark.png", blob.read_bytes(), "image/png")},
    )
    assert uploaded.status_code == 200
    asset_name = uploaded.json()["asset_name"]
    fetched = client.get(f"/studio/overlay-assets/{asset_name}")
    assert fetched.status_code == 200
    assert fetched.headers["content-type"].startswith("image/png")
    missing = client.get("/studio/overlay-assets/../secret.png")
    assert missing.status_code == 404
    bad = client.post(
        "/api/studio/overlay-assets",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert bad.status_code == 400


def test_ffmpeg_accepts_overlay_graph(tmp_path: Path) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    import subprocess

    overlay = Overlay(
        id="ovtext0001",
        kind="rectangle",
        start_s=0,
        end_s=0.2,
        x=0.1,
        y=0.1,
        w=0.3,
        h=0.3,
    )
    png = tmp_path / "box.png"
    render_overlay_png(
        overlay,
        frame_width=320,
        frame_height=180,
        source_width=320,
        source_height=180,
        asset_path=None,
        dest=png,
    )
    graph = ffmpeg_overlay_graph(
        base_chain="scale=320:180,format=yuv420p",
        fades=[],
        windows=[(0.0, 0.2)],
        first_input=1,
    )
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x335577:s=320x180:r=30:d=0.2",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(png),
            "-filter_complex",
            graph,
            "-map",
            "[vout]",
            "-frames:v",
            "2",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")


def test_animation_presets_are_bounded_and_numeric() -> None:
    from orga_drone.studio_overlay import OverlayWindow

    plain, _changed = parse_overlays([_text()], duration_s=8)
    assert plain[0].animation == "none"
    faded, clamped = parse_overlays(
        [_text(animation="fade_in", animation_s=9, start_s=0, end_s=1)],
        duration_s=8,
    )
    assert clamped is True
    assert faded[0].animation == "fade_in"
    assert faded[0].animation_s <= 1
    with pytest.raises(ValueError, match="animation"):
        parse_overlays([_text(animation="keyframes")], duration_s=8)
    fade_graph = ffmpeg_overlay_graph(
        base_chain="scale=320:180",
        fades=[],
        windows=[OverlayWindow(start_s=4, end_s=8, animation="fade_in", animation_s=0.4)],
        first_input=1,
    )
    assert "fade=t=in:st=4.0000:d=0.4000:alpha=1" in fade_graph
    assert "drawtext" not in fade_graph
    out_graph = ffmpeg_overlay_graph(
        base_chain="scale=320:180",
        fades=[],
        windows=[OverlayWindow(start_s=1, end_s=3, animation="fade_out", animation_s=0.5)],
        first_input=1,
    )
    assert "fade=t=out:st=2.5000:d=0.5000:alpha=1" in out_graph
    slide = ffmpeg_overlay_graph(
        base_chain="scale=320:180",
        fades=[],
        windows=[
            OverlayWindow(
                start_s=0,
                end_s=2,
                animation="slide_in",
                animation_s=0.4,
                slide_from="left",
                px=40,
                py=20,
                pw=30,
                ph=12,
                ox=10,
                oy=0,
                cw=300,
                ch=180,
            )
        ],
        first_input=1,
    )
    assert "overlay=x=" in slide
    assert "Landmark" not in slide
    assert ",draw" not in slide
    script = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    assert "function animationOpacity" in script
    assert "fade_out" in script
    assert "slide_in" in script

