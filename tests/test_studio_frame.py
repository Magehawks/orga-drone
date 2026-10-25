"""Per-clip Studio zoom and pan (Issue #86)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.export.studio_config import StudioExportClip, StudioExportConfig
from orga_drone.export.studio_encoder import (
    FfmpegStudioEncoder,
    _segment_vf,
    _segment_vf_for_clip,
    build_stitch_filters,
)
from orga_drone.ffmpeg_bin import find_ffmpeg
from orga_drone.studio_export import _clip_to_export_clip
from orga_drone.studio_frame import (
    FrameTransform,
    content_rect,
    dump_frame,
    ffmpeg_frame_prefix,
    frame_from_effect_settings,
    parse_frame_payload,
    sample_frame,
    window_for,
)
from orga_drone.studio_image import ImageAdjust, image_adjust_from_effect_settings


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
    if not media_file.exists():
        media_file.write_bytes(b"media")
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": kind,
            "filename": filename,
            "path": str(media_file.resolve()),
            "size_bytes": media_file.stat().st_size,
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
        identity_key=make_identity_key(
            item.filename, item.size_bytes, item.recorded_at
        ),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
    )
    return clip_id


def _video(**overrides: object) -> StudioExportClip:
    values: dict[str, object] = {
        "source_path": Path("clip.mp4"),
        "kind": "video",
        "duration_s": 4.0,
    }
    values.update(overrides)
    return StudioExportClip(**values)  # type: ignore[arg-type]


def _marker_image(path: Path, *, width: int, height: int, box: int = 40) -> None:
    image = Image.new("RGB", (width, height), (0, 0, 0))
    left = (width - box) // 2
    top = (height - box) // 2
    white = Image.new("RGB", (box, box), (255, 255, 255))
    image.paste(white, (left, top))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="JPEG", quality=95)


def _white_count(path: Path) -> int:
    with Image.open(path) as image:
        pixels = image.convert("RGB").getdata()
    return sum(
        1 for pixel in pixels if pixel[0] > 200 and pixel[1] > 200 and pixel[2] > 200
    )


def _extract_png(video: Path, png: Path, at_s: float) -> None:
    ffmpeg = find_ffmpeg()
    assert ffmpeg
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-ss",
            f"{at_s:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            str(png),
        ],
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")


def test_missing_frame_is_identity_and_payload_is_bounded() -> None:
    for raw in (None, "", "{}", "{", "[]", '{"frame":"nope"}'):
        assert frame_from_effect_settings(raw).is_neutral
    hostile = frame_from_effect_settings(
        '{"frame":{"zoom_start":9,"zoom_end":true,"x_start":"crop=1"}}'
    )
    assert hostile.is_neutral
    parsed = parse_frame_payload(
        {
            "zoom_start": 2.04,
            "zoom_end": 2.04,
            "x_start": -2,
            "y_start": 1.4,
            "x_end": 0.2,
            "y_end": 0.8,
        }
    )
    assert parsed.zoom_start == 2.04
    assert parsed.x_start == 0.0
    assert parsed.y_start == 1.0
    assert parsed.is_animated
    assert not parse_frame_payload({"zoom_start": 2, "zoom_end": 2}).is_animated
    with pytest.raises(ValueError):
        parse_frame_payload({"zoom_start": True})
    with pytest.raises(ValueError):
        parse_frame_payload({"zoom_start": 3.5})
    with pytest.raises(ValueError):
        parse_frame_payload({"zoom_start": "1;crop=1"})
    blob = dump_frame('{"image":{"exposure":4}}', parsed)
    stored = json.loads(blob)
    assert stored["image"]["exposure"] == 4
    assert stored["frame"]["zoom_start"] == 2.04
    assert image_adjust_from_effect_settings(blob).exposure == 4


def test_neutral_chain_is_unchanged_and_zoom_crops_inside_the_picture() -> None:
    plain = _video()
    assert _segment_vf_for_clip(1920, 1080, plain) == _segment_vf(1920, 1080)
    zoomed = _video(
        frame=FrameTransform(
            zoom_start=2,
            zoom_end=2,
            x_start=0.25,
            y_start=0.75,
            x_end=0.25,
            y_end=0.75,
        ),
        fade_in_s=0.2,
    )
    vf = _segment_vf_for_clip(1280, 720, zoomed)
    assert "crop=" in vf
    assert vf.index("scale=") < vf.index("crop=")
    assert vf.index("crop=") < vf.index("fade=t=in")
    landscape = window_for(
        2,
        0.25,
        0.75,
        frame_width=1280,
        frame_height=720,
        source_width=1920,
        source_height=1080,
    )
    portrait = window_for(
        2,
        0.5,
        0.5,
        frame_width=1280,
        frame_height=720,
        source_width=1080,
        source_height=1920,
    )
    origin_x, origin_y, content_w, content_h = content_rect(1280, 720, 1080, 1920)
    assert portrait[0] >= origin_x
    assert portrait[1] >= origin_y
    assert portrait[0] + portrait[2] <= origin_x + content_w
    assert portrait[1] + portrait[3] <= origin_y + content_h
    assert landscape[2] != portrait[2]
    for width, height in ((1280, 720), (1920, 1080)):
        left, top, view_w, view_h = window_for(
            2,
            0.25,
            0.75,
            frame_width=width,
            frame_height=height,
            source_width=1920,
            source_height=1080,
        )
        ox, oy, cw, ch = content_rect(width, height, 1920, 1080)
        assert abs((left + view_w / 2 - ox) / cw - 0.25) < 0.02
        assert abs((top + view_h / 2 - oy) / ch - 0.75) < 0.02
    card = StudioExportClip(
        source_path=None,
        kind="title_card",
        duration_s=3.0,
        frame=FrameTransform(zoom_start=2, zoom_end=2),
    )
    assert "crop=" not in _segment_vf_for_clip(1280, 720, card)


def test_animation_uses_trimmed_source_time_and_stitch_stays_plain() -> None:
    frame = FrameTransform(
        zoom_start=1.2,
        zoom_end=2.5,
        x_start=0.2,
        y_start=0.3,
        x_end=0.8,
        y_end=0.7,
    )
    prefix = ffmpeg_frame_prefix(
        frame,
        source_width=1920,
        source_height=1080,
        kind="video",
        source_start_s=1.5,
        duration_s=2.0,
    )
    assert prefix.startswith("zoompan=")
    assert "(time-1.5000)/2.0000" in prefix
    assert "1.2000" in prefix
    assert "1.3000" in prefix
    assert "s=1920x1080" in prefix
    assert ";" not in prefix
    assert "file" not in prefix
    photo = ffmpeg_frame_prefix(
        frame,
        source_width=640,
        source_height=360,
        kind="photo",
        source_start_s=4,
        duration_s=3,
    )
    assert "(time-0.0000)/3.0000" in photo
    start = sample_frame(frame, 0)
    end = sample_frame(frame, 1)
    assert start[0] == pytest.approx(1.2)
    assert end[0] == pytest.approx(2.5)
    left = _video(
        frame=frame,
        source_start_s=1.5,
        transition_type="crossfade",
        transition_s=0.4,
    )
    right = _video(source_path=Path("right.mp4"), image=ImageAdjust(exposure=10))
    stitch = ";".join(build_stitch_filters((left, right)))
    assert "xfade=" in stitch
    assert "crop=" not in stitch
    assert "zoompan=" not in stitch
    graded = _segment_vf_for_clip(1280, 720, right)
    assert graded.startswith("exposure=")
    assert "crop=" not in graded


def test_export_zoom_enlarges_the_subject_and_motion_reaches_the_end(
    tmp_path: Path,
) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    still = tmp_path / "marker.jpg"
    _marker_image(still, width=640, height=360, box=48)
    portrait = tmp_path / "portrait.jpg"
    _marker_image(portrait, width=200, height=400, box=36)

    def render(
        name: str, source: Path, kind: str, frame: FrameTransform, **extra: object
    ) -> Path:
        out = tmp_path / name
        values: dict[str, object] = {
            "source_path": source,
            "kind": kind,
            "duration_s": 1.0,
            "frame": frame,
        }
        values.update(extra)
        clip = StudioExportClip(**values)  # type: ignore[arg-type]
        FfmpegStudioEncoder().render(
            StudioExportConfig(
                output_path=out,
                width=320,
                height=180,
                clips=(clip,),
            )
        )
        return out

    neutral = render("neutral.mp4", still, "photo", FrameTransform())
    zoomed = render(
        "zoomed.mp4",
        still,
        "photo",
        FrameTransform(zoom_start=2, zoom_end=2),
    )
    neutral_png = tmp_path / "neutral.png"
    zoomed_png = tmp_path / "zoomed.png"
    _extract_png(neutral, neutral_png, 0.2)
    _extract_png(zoomed, zoomed_png, 0.2)
    neutral_white = _white_count(neutral_png)
    zoomed_white = _white_count(zoomed_png)
    assert zoomed_white > neutral_white * 1.5
    with Image.open(neutral_png) as image:
        assert image.getpixel((0, image.height // 2))[0] < 30
    with Image.open(zoomed_png) as image:
        assert image.getpixel((0, image.height // 2))[0] < 30

    portrait_out = render(
        "portrait.mp4",
        portrait,
        "photo",
        FrameTransform(zoom_start=2, zoom_end=2, x_start=0, y_start=0),
    )
    portrait_png = tmp_path / "portrait.png"
    _extract_png(portrait_out, portrait_png, 0.2)
    with Image.open(portrait_png) as image:
        assert image.getpixel((0, image.height // 2))[0] < 30
        assert image.getpixel((image.width - 1, image.height // 2))[0] < 30

    source_video = tmp_path / "source.mp4"
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-i",
            str(still),
            "-t",
            "3",
            "-r",
            "30",
            "-pix_fmt",
            "yuv420p",
            str(source_video),
        ],
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    moved = render(
        "moved.mp4",
        source_video,
        "video",
        FrameTransform(zoom_start=1, zoom_end=3, x_start=0.5, y_start=0.5),
        source_start_s=1.0,
        source_end_s=2.0,
        duration_s=1.0,
    )
    begin = tmp_path / "begin.png"
    finish = tmp_path / "finish.png"
    _extract_png(moved, begin, 0.05)
    _extract_png(moved, finish, 0.85)
    assert _white_count(finish) > _white_count(begin) * 1.4


def test_frame_persists_through_cut_and_keeps_image_settings(tmp_path: Path) -> None:
    db = Database(tmp_path / "studio.sqlite3")
    media_id = _seed_media(
        db, tmp_path / "lib", filename="cloud.MP4", kind="video", duration_s=8.0
    )
    first = _add(db, media_id)
    db.set_studio_image_adjust(first, {"exposure": 12})
    stored = db.set_studio_frame(
        first,
        {
            "frame": {
                "zoom_start": 1.5,
                "zoom_end": 2.25,
                "x_start": 0.2,
                "y_start": 0.3,
                "x_end": 0.8,
                "y_end": 0.7,
            }
        },
    )
    assert image_adjust_from_effect_settings(stored.effect_settings).exposure == 12
    reopened = Database(tmp_path / "studio.sqlite3")
    item = {row.id: row for row in reopened.list_studio_items()}[first]
    frame = frame_from_effect_settings(item.effect_settings)
    assert frame.zoom_end == 2.25
    assert frame.x_end == 0.8
    exported = _clip_to_export_clip(reopened, item)
    assert exported is not None
    assert exported.frame.zoom_start == 1.5
    assert exported.image.exposure == 12
    left, right = reopened.cut_studio_video_item(first, 2.0)
    assert frame_from_effect_settings(left.effect_settings).y_end == 0.7
    assert frame_from_effect_settings(right.effect_settings).zoom_start == 1.5
    card = reopened.add_studio_title_card(
        reopened.list_studio_projects()[0].id, title_text="Hi"
    )
    with pytest.raises(ValueError, match="photos and videos"):
        reopened.set_studio_frame(card.id, {"zoom_start": 2})
    missing = reopened.set_studio_image_adjust(right.id, {"contrast": 5})
    assert frame_from_effect_settings(missing.effect_settings).zoom_end == 2.25


def test_http_frame_validation_and_inspector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    video_id = _add(
        db,
        _seed_media(
            db, tmp_path / "lib", filename="V.MP4", kind="video", duration_s=6.0
        ),
    )
    photo_id = _add(
        db,
        _seed_media(
            db, tmp_path / "lib", filename="P.JPG", kind="photo", duration_s=None
        ),
    )
    client = TestClient(app)
    page = client.get("/studio")
    assert page.status_code == 200
    assert 'id="inspector-frame" data-inspector-tab="image" hidden' in page.text
    assert 'id="inspector-frame-zoom"' in page.text
    assert 'id="inspector-frame-motion"' in page.text
    assert ("Bildausschnitt" in page.text) or ("Framing" in page.text)
    assert "data-frame=" in page.text
    script = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    assert "frameWrap.hidden = !(isPhoto || isVideo)" in script

    rejected = client.patch(
        f"/api/studio/{video_id}/frame",
        json={"zoom_start": "1;crop=1"},
    )
    assert rejected.status_code == 400
    stored = {item.id: item for item in db.list_studio_items()}[video_id]
    assert frame_from_effect_settings(stored.effect_settings).is_neutral
    too_far = client.patch(f"/api/studio/{video_id}/frame", json={"zoom_start": 4})
    assert too_far.status_code == 400
    saved = client.patch(
        f"/api/studio/{photo_id}/frame",
        json={"zoom_start": 1.25, "zoom_end": 2, "x_start": 0.1, "y_end": 0.9},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["frame"]["zoom_start"] == 1.25
    assert body["frame"]["zoom_end"] == 2
    assert body["frame"]["y_end"] == 0.9
    card = db.add_studio_title_card(db.list_studio_projects()[0].id, title_text="Hi")
    blocked = client.patch(f"/api/studio/{card.id}/frame", json={"zoom_start": 2})
    assert blocked.status_code == 400
