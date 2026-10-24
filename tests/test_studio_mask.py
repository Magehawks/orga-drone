"""Per-clip Studio privacy masks (Issue #81)."""

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
    StudioExportError,
    _segment_vf,
    _segment_vf_for_clip,
    _segment_video_args,
    build_stitch_filters,
)
from orga_drone.ffmpeg_bin import find_ffmpeg
from orga_drone.studio_export import _clip_to_export_clip
from orga_drone.studio_image import image_adjust_from_effect_settings
from orga_drone.studio_mask import (
    Mask,
    content_rect,
    dump_masks,
    ffmpeg_mask_graph,
    mask_box_pixels,
    mask_windows,
    masks_from_effect_settings,
    parse_masks_payload,
    pixel_block_px,
)


def _mask(**overrides: object) -> Mask:
    values: dict[str, object] = {
        "id": "mabc1234567",
        "effect": "blur",
        "strength": 80,
        "x": 0.25,
        "y": 0.0,
        "w": 0.5,
        "h": 1.0,
    }
    values.update(overrides)
    return Mask(**values)  # type: ignore[arg-type]


def _seed_media(db: Database, root_path: Path, *, filename: str, kind: str) -> int:
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
            "duration_s": 6.0 if kind == "video" else None,
            "recorded_at": "2024-06-01T12:00:00",
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


def test_parse_clamps_and_rejects_bad_values() -> None:
    masks = parse_masks_payload(
        {
            "masks": [
                {
                    "id": "keep_me",
                    "effect": "blur",
                    "strength": 12.2,
                    "x": -4,
                    "y": 0.1,
                    "w": 0.01,
                    "h": 2,
                },
                {"effect": "pixelate", "strength": 90, "x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2},
            ]
        }
    )
    assert len(masks) == 2
    assert masks[0].id == "keep_me"
    assert masks[0].x == 0
    assert masks[0].w == 0.04
    assert masks[0].h == 1
    assert masks[0].strength == 12
    assert masks[1].effect == "pixelate"
    assert masks[1].id != masks[0].id
    with pytest.raises(ValueError, match="effect"):
        parse_masks_payload({"masks": [{"effect": "blur;movie=/tmp/x", "strength": 10}]})
    with pytest.raises(ValueError, match="strength"):
        parse_masks_payload({"masks": [{"effect": "blur", "strength": True}]})
    with pytest.raises(ValueError, match="at most"):
        parse_masks_payload(
            {"masks": [{"effect": "blur", "strength": 10} for _ in range(9)]}
        )
    blob = dump_masks('{"image":{"exposure":4}}', masks)
    stored = json.loads(blob)
    assert stored["image"]["exposure"] == 4
    assert "movie" not in blob
    hostile = masks_from_effect_settings(
        '{"masks":[{"effect":"blur;drawtext","strength":"no"},{"effect":"pixelate","strength":40}]}'
    )
    assert len(hostile) == 1
    assert hostile[0].effect == "pixelate"


def test_letterbox_box_scales_between_resolutions() -> None:
    mask = _mask(x=0.0, y=0.1, w=0.2, h=0.3)
    portrait = (1080, 1920)
    boxes = []
    for frame in ((1280, 720), (1920, 1080)):
        rect = content_rect(*frame, *portrait)
        left, top, width, height = mask_box_pixels(
            mask, rect, frame_width=frame[0], frame_height=frame[1]
        )
        origin_x, origin_y, content_w, content_h = rect
        assert left > 0
        assert origin_x > 0
        boxes.append(
            (
                (left - origin_x) / content_w,
                (top - origin_y) / content_h,
                width / content_w,
                height / content_h,
            )
        )
    for a, b in zip(boxes[0], boxes[1]):
        assert a == pytest.approx(b, abs=0.02)
    small = pixel_block_px(100, 720, 720, 200, 200)
    large = pixel_block_px(100, 1080, 1080, 300, 300)
    assert large > small


def test_graph_is_numeric_and_neutral_vf_is_unchanged() -> None:
    plain = StudioExportClip(source_path=Path("clip.mp4"), kind="video", duration_s=4)
    assert _segment_video_args(plain, 1920, 1080) == ["-vf", _segment_vf(1920, 1080)]
    assert _segment_vf_for_clip(1920, 1080, plain) == _segment_vf(1920, 1080)
    windows = mask_windows(
        (_mask(id="evil;drawtext"), _mask(id="msecond2345", effect="pixelate", x=0.6)),
        frame_width=320,
        frame_height=180,
        source_width=320,
        source_height=180,
    )
    graph = ffmpeg_mask_graph(
        base_chain=_segment_vf(320, 180),
        fades=["fade=t=in:st=0:d=0.2000"],
        windows=windows,
    )
    assert "boxblur=" in graph
    assert "flags=neighbor" in graph
    assert "drawtext" not in graph
    assert "evil" not in graph
    assert graph.endswith("format=yuv420p[vout]")
    assert graph.index("boxblur=") < graph.index("fade=t=in")
    masked = StudioExportClip(
        source_path=Path("clip.mp4"),
        kind="video",
        duration_s=4,
        masks=(_mask(),),
        transition_type="crossfade",
        transition_s=0.4,
    )
    with pytest.raises(RuntimeError, match="_segment_video_args"):
        _segment_vf_for_clip(320, 180, masked)
    other = StudioExportClip(
        source_path=Path("b.mp4"),
        kind="video",
        duration_s=2,
        masks=(_mask(effect="pixelate"),),
    )
    stitch = ";".join(build_stitch_filters((masked, other)))
    assert "xfade=" in stitch
    assert "boxblur" not in stitch
    assert "overlay=" not in stitch


def test_masks_persist_per_clip_and_survive_cut(tmp_path: Path) -> None:
    db = Database(tmp_path / "studio.sqlite3")
    media_id = _seed_media(db, tmp_path / "lib", filename="cloud.MP4", kind="video")
    first = _add(db, media_id)
    second = _add(db, media_id)
    db.set_studio_image_adjust(first, {"exposure": 15})
    db.set_studio_masks(
        first,
        {
            "masks": [
                {"id": "mblur000001", "effect": "blur", "strength": 40, "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.2},
                {"effect": "pixelate", "strength": 70, "x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2},
            ]
        },
    )
    db.set_studio_masks(
        second,
        {"masks": [{"effect": "blur", "strength": 20, "x": 0.2, "y": 0.2, "w": 0.2, "h": 0.2}]},
    )
    reopened = Database(tmp_path / "studio.sqlite3")
    by_id = {item.id: item for item in reopened.list_studio_items()}
    stored = masks_from_effect_settings(by_id[first].effect_settings)
    assert len(stored) == 2
    assert stored[0].effect == "blur"
    assert stored[1].effect == "pixelate"
    assert image_adjust_from_effect_settings(by_id[first].effect_settings).exposure == 15
    assert len(masks_from_effect_settings(by_id[second].effect_settings)) == 1
    exported = _clip_to_export_clip(reopened, by_id[first])
    assert exported is not None
    assert len(exported.masks) == 2
    left, right = reopened.cut_studio_video_item(first, 2.0)
    assert len(masks_from_effect_settings(left.effect_settings)) == 2
    assert len(masks_from_effect_settings(right.effect_settings)) == 2
    card = reopened.add_studio_title_card(left.project_id, title_text="Hello")
    with pytest.raises(ValueError, match="photos and videos"):
        reopened.set_studio_masks(card.id, {"masks": []})


def test_http_masks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    db = app.state.db
    media_id = _seed_media(db, tmp_path / "lib", filename="still.jpg", kind="photo")
    clip_id = _add(db, media_id)
    client = TestClient(app)
    saved = client.patch(
        f"/api/studio/{clip_id}/masks",
        json={
            "masks": [
                {"id": "mphoto00001", "effect": "blur", "strength": 55, "x": 0.2, "y": 0.2, "w": 0.3, "h": 0.25},
                {"effect": "pixelate", "strength": 80, "x": 0.6, "y": 0.1, "w": 0.2, "h": 0.2},
            ]
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert len(body["masks"]) == 2
    kept_id = body["masks"][0]["id"]
    removed_id = body["masks"][1]["id"]
    page = client.get("/studio")
    assert page.status_code == 200
    assert "data-masks='" in page.text
    assert kept_id in page.text
    assert removed_id in page.text
    assert "Datenschutz" in page.text
    assert "studio-inspector-resize" in page.text
    assert "inspector-tab-effects" in page.text
    removed = client.patch(
        f"/api/studio/{clip_id}/masks",
        json={"masks": [body["masks"][0]]},
    )
    assert removed.status_code == 200
    assert [row["id"] for row in removed.json()["masks"]] == [kept_id]
    again = client.get("/studio")
    assert kept_id in again.text
    assert removed_id not in again.text
    project = db.get_open_studio_project()
    assert project is not None
    items = db.list_studio_items(project.id)
    export_clip = _clip_to_export_clip(db, items[0])
    assert export_clip is not None
    assert [mask.id for mask in export_clip.masks] == [kept_id]
    missing = client.patch("/api/studio/99999/masks", json={"masks": []})
    assert missing.status_code == 404


def _split_jpeg(path: Path) -> None:
    image = Image.new("RGB", (64, 64), (0, 0, 0))
    white = Image.new("RGB", (32, 64), (255, 255, 255))
    image.paste(white, (32, 0))
    image.save(path, "JPEG", quality=95)


def _luma(pixel: object) -> int:
    if isinstance(pixel, int):
        return pixel
    return int(pixel[0])  # type: ignore[index]


def _assert_split_is_masked(frame: Path, *, width: int, height: int) -> None:
    mask = _mask()
    rect = content_rect(width, height, 64, 64)
    left, top, box_w, box_h = mask_box_pixels(
        mask, rect, frame_width=width, frame_height=height
    )
    with Image.open(frame) as image:
        center = _luma(image.getpixel((left + box_w // 2, top + box_h // 2)))
        before = _luma(image.getpixel((left - 4, top + box_h // 2)))
        after = _luma(image.getpixel((left + box_w + 4, top + box_h // 2)))
    assert before < 40
    assert after > 200
    assert 40 < center < 220


def test_photo_and_video_exports_mask_the_boundary(tmp_path: Path) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    still = tmp_path / "split.jpg"
    _split_jpeg(still)
    video = tmp_path / "split.mp4"
    made = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-i",
            str(still),
            "-t",
            "0.3",
            "-vf",
            "fps=30,format=yuv420p",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        capture_output=True,
        check=False,
    )
    assert made.returncode == 0, made.stderr.decode("utf-8", errors="replace")
    mask = _mask()
    photo_out = tmp_path / "photo.mp4"
    video_out = tmp_path / "video.mp4"
    encoder = FfmpegStudioEncoder()
    encoder.render(
        StudioExportConfig(
            output_path=photo_out,
            width=160,
            height=90,
            clips=(
                StudioExportClip(
                    source_path=still,
                    kind="photo",
                    duration_s=0.3,
                    masks=(mask,),
                ),
            ),
        )
    )
    encoder.render(
        StudioExportConfig(
            output_path=video_out,
            width=320,
            height=180,
            clips=(
                StudioExportClip(
                    source_path=video,
                    kind="video",
                    duration_s=0.3,
                    masks=(mask,),
                ),
            ),
        )
    )
    for src, dest, size in (
        (photo_out, tmp_path / "photo.png", (160, 90)),
        (video_out, tmp_path / "video.png", (320, 180)),
    ):
        grabbed = subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-frames:v", "1", str(dest)],
            capture_output=True,
            check=False,
        )
        assert grabbed.returncode == 0, grabbed.stderr.decode("utf-8", errors="replace")
        _assert_split_is_masked(dest, width=size[0], height=size[1])


def test_mask_failure_does_not_write_unmasked_export(tmp_path: Path) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    source = tmp_path / "broken.mp4"
    source.write_bytes(b"not a video")
    dest = tmp_path / "out.mp4"
    with pytest.raises(StudioExportError, match="privacy mask"):
        FfmpegStudioEncoder().render(
            StudioExportConfig(
                output_path=dest,
                width=160,
                height=90,
                clips=(
                    StudioExportClip(
                        source_path=source,
                        kind="video",
                        duration_s=0.3,
                        masks=(_mask(),),
                    ),
                ),
            )
        )
    assert not dest.exists()
