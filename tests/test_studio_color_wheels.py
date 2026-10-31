"""Per-clip Studio colour wheels (Issue #232 follow-up)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageChops, ImageStat

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.export.studio_config import StudioExportClip, StudioExportConfig
from orga_drone.export.studio_encoder import FfmpegStudioEncoder, _segment_vf_for_clip
from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.studio_detail import DetailEnhance
from orga_drone.studio_color_wheels import (
    WHEEL_IDS,
    ColorWheelPoint,
    ColorWheels,
    apply_color_wheels_rgb,
    color_wheels_from_effect_settings,
    dump_color_wheels,
    ffmpeg_color_wheels_chain,
    hue_tint_vector,
    parse_color_wheels_payload,
    tonal_weights,
)
from orga_drone.studio_hsl import HslAdjust, HslRange
from orga_drone.studio_image import ImageAdjust
from orga_drone.studio_lut import ColorLook, import_lut_from_path, write_identity_cube
from orga_drone.studio_preview_frame import (
    PreviewFrameRequest,
    preview_filter_chain,
    render_preview_frame,
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


def _add(db: Database, media_id: int, project_id: int | None = None) -> int:
    item = db.get_media(media_id)
    assert item is not None
    clip_id, _created = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
        project_id=project_id,
        source_media_id=media_id,
    )
    return clip_id


def _ffmpeg() -> str:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    return ffmpeg


def _run(ffmpeg: str, *args: str) -> None:
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", *args],
        check=True,
        capture_output=True,
        timeout=60,
        **subprocess_no_window_kwargs(),
    )


def _make_photo(path: Path, *, color: str = "0x4060A0") -> Path:
    ffmpeg = _ffmpeg()
    path.parent.mkdir(parents=True, exist_ok=True)
    _run(ffmpeg, "-f", "lavfi", "-i", f"color=c={color}:s=320x180:d=0.1",
         "-frames:v", "1", str(path))
    return path


def test_neutral_wheels_are_identity_and_old_projects_load() -> None:
    wheels = ColorWheels()
    assert wheels.is_neutral
    assert apply_color_wheels_rgb(0.2, 0.5, 0.8, wheels) == (0.2, 0.5, 0.8)
    assert ffmpeg_color_wheels_chain(wheels, data_dir=Path("unused")) == ""
    for raw in (None, "", "{}", "{", "[]", '{"color_wheels":"nope"}', '{"color_wheels":{"wheels":[]}}'):
        assert color_wheels_from_effect_settings(raw).is_neutral
    blob = dump_color_wheels('{"image":{"exposure":10}}', ColorWheels())
    stored = json.loads(blob)
    assert stored["image"]["exposure"] == 10
    assert stored["color_wheels"]["wheels"]["shadows"] == {"x": 0.0, "y": 0.0}


def test_tonal_weights_are_smooth_and_sum_to_one() -> None:
    for luma in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0):
        weights = tonal_weights(luma)
        assert sum(weights) == pytest.approx(1.0)
        assert all(0.0 <= weight <= 1.0 for weight in weights)
    assert tonal_weights(0.0) == pytest.approx((1.0, 0.0, 0.0))
    assert tonal_weights(0.5) == pytest.approx((0.0, 1.0, 0.0))
    assert tonal_weights(1.0) == pytest.approx((0.0, 0.0, 1.0))
    assert tonal_weights(0.25) == pytest.approx((0.5, 0.5, 0.0))
    left = tonal_weights(0.499)
    right = tonal_weights(0.501)
    assert max(abs(a - b) for a, b in zip(left, right)) < 0.001


def test_wheel_tints_are_zero_luma_and_tonally_independent() -> None:
    for hue in (0, 45, 120, 240, 300):
        vector = hue_tint_vector(hue)
        luma = 0.2126 * vector[0] + 0.7152 * vector[1] + 0.0722 * vector[2]
        assert luma == pytest.approx(0.0, abs=1e-9)

    red_shadows = ColorWheels(shadows=ColorWheelPoint(x=1.0, y=0.0))
    black = apply_color_wheels_rgb(0.0, 0.0, 0.0, red_shadows)
    assert black[0] > 0.1
    assert black[1] == 0.0
    assert apply_color_wheels_rgb(1.0, 1.0, 1.0, red_shadows) == pytest.approx((1.0, 1.0, 1.0))

    blue_highlights = ColorWheels(highlights=ColorWheelPoint(x=-1.0, y=0.0))
    white = apply_color_wheels_rgb(1.0, 1.0, 1.0, blue_highlights)
    assert white[2] == 1.0
    assert white[0] < 1.0
    assert apply_color_wheels_rgb(0.0, 0.0, 0.0, blue_highlights) == pytest.approx((0.0, 0.0, 0.0))

    mid = apply_color_wheels_rgb(0.5, 0.5, 0.5, ColorWheels(midtones=ColorWheelPoint(x=1.0, y=0.0)))
    assert mid[0] > 0.5
    assert mid[1] < 0.5

    # All three wheels stay independent and combine.
    combined = ColorWheels(
        shadows=ColorWheelPoint(x=1.0, y=0.0),
        midtones=ColorWheelPoint(x=-1.0, y=0.0),
        highlights=ColorWheelPoint(x=0.0, y=1.0),
    )
    assert apply_color_wheels_rgb(0.0, 0.0, 0.0, combined)[0] > 0.0
    assert apply_color_wheels_rgb(0.5, 0.5, 0.5, combined)[0] < 0.5
    assert apply_color_wheels_rgb(1.0, 1.0, 1.0, combined)[2] < 1.0


def test_parse_clamps_to_the_disc_and_rejects_bad_input() -> None:
    current = ColorWheels(shadows=ColorWheelPoint(x=0.1, y=0.2))
    updated = parse_color_wheels_payload(
        {"wheel": "midtones", "x": 2.0, "y": 0.0}, current
    )
    assert updated.shadows == ColorWheelPoint(x=0.1, y=0.2)
    assert updated.midtones == ColorWheelPoint(x=1.0, y=0.0)
    updated = parse_color_wheels_payload(
        {"wheels": {"highlights": {"x": 1.0, "y": 1.0}}}, updated
    )
    assert updated.highlights.radius == pytest.approx(1.0, abs=1e-4)
    with pytest.raises(ValueError, match="colour wheel"):
        parse_color_wheels_payload({"wheel": "pink", "x": 0.1}, current)
    with pytest.raises(ValueError, match="colour wheel"):
        parse_color_wheels_payload({"image": {}}, current)
    corrupt = color_wheels_from_effect_settings(
        '{"color_wheels":{"wheels":{"shadows":{"x":900,"y":"x"},"midtones":{"x":0.4,"y":-0.2}}}}'
    )
    assert corrupt.shadows.is_neutral
    assert corrupt.midtones == ColorWheelPoint(x=0.4, y=-0.2)


def test_settings_persist_per_clip(tmp_path: Path) -> None:
    db = Database(tmp_path / "studio.sqlite3")
    media_id = _seed_media(
        db, tmp_path / "lib", filename="cloud.MP4", kind="video", duration_s=8.0
    )
    first = _add(db, media_id)
    second = _add(db, media_id)
    db.set_studio_color_wheels(first, {"wheels": {"shadows": {"x": 0.3, "y": -0.2}}})
    db.set_studio_color_wheels(second, {"wheels": {"highlights": {"x": -0.4, "y": 0.1}}})
    items = {item.id: item for item in db.list_studio_items(1)}
    first_wheels = color_wheels_from_effect_settings(items[first].effect_settings)
    second_wheels = color_wheels_from_effect_settings(items[second].effect_settings)
    assert first_wheels.shadows == ColorWheelPoint(x=0.3, y=-0.2)
    assert first_wheels.highlights.is_neutral
    assert second_wheels.highlights == ColorWheelPoint(x=-0.4, y=0.1)
    assert second_wheels.shadows.is_neutral


def test_export_chain_order_after_hsl_before_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setattr("orga_drone.config.settings", Settings(data_dir=data_dir))
    asset = import_lut_from_path(
        data_dir, write_identity_cube(tmp_path / "identity.cube")
    )
    wheels = ColorWheels(shadows=ColorWheelPoint(x=0.4, y=-0.2))
    clip = StudioExportClip(
        Path("clip.mp4"),
        "video",
        4.0,
        image=ImageAdjust(exposure=10),
        color_look=ColorLook(creative_lut=asset, creative_strength=100),
        hsl=HslAdjust(blue=HslRange(hue=20)),
        color_wheels=wheels,
        detail=DetailEnhance(sharpen=20),
    )
    export_vf = _segment_vf_for_clip(320, 180, clip)
    assert export_vf.count("lut3d=") == 3
    first = export_vf.index("lut3d=")
    second = export_vf.index("lut3d=", first + 1)
    third = export_vf.index("lut3d=", second + 1)
    assert "hsl-luts" not in export_vf[first:second]
    assert "hsl-luts" in export_vf[second:third]
    assert "color-wheel-luts" in export_vf[third:]
    preview_vf = preview_filter_chain(
        clip.image,
        clip.color_look,
        hsl=clip.hsl,
        color_wheels=wheels,
        data_dir=data_dir,
        work_dir=tmp_path / "work",
    )
    assert preview_vf.count("lut3d=") == 3
    assert "color-wheel-luts" in preview_vf
    # Neutral wheels leave the existing grade + LUT + HSL chain unchanged.
    preview_plain = preview_filter_chain(
        clip.image, clip.color_look, hsl=clip.hsl, data_dir=data_dir, work_dir=tmp_path / "work"
    )
    assert preview_filter_chain(
        clip.image,
        clip.color_look,
        hsl=clip.hsl,
        color_wheels=ColorWheels(),
        data_dir=data_dir,
        work_dir=tmp_path / "work",
    ) == preview_plain


def test_color_wheel_api_and_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from orga_drone.app import create_app

    data_dir = tmp_path / "data"
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=data_dir))
    app = create_app()
    db: Database = app.state.db
    root = tmp_path / "media"
    root.mkdir()
    root_id = db.add_root(root, label="t")
    photo = _make_photo(root / "shot.jpg")
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": photo.name,
            "path": str(photo.resolve()),
            "size_bytes": photo.stat().st_size,
            "duration_s": None,
            "recorded_at": "2024-01-01T00:00:00",
            "sequence": None,
            "mode": None,
            "drone_model": None,
            "camera_model": None,
            "latitude": None,
            "longitude": None,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )
    clip_id = _add(db, media_id)
    client = TestClient(app)
    denied = client.get(f"/api/studio/{clip_id}/preview-frame")
    assert denied.status_code == 422
    saved = client.patch(
        f"/api/studio/{clip_id}/color-wheels",
        json={"wheels": {"shadows": {"x": 0.4, "y": -0.2}}},
    )
    assert saved.status_code == 200
    assert saved.json()["color_wheels"]["wheels"]["shadows"] == {"x": 0.4, "y": -0.2}
    still = client.get(f"/api/studio/{clip_id}/preview-frame")
    assert still.status_code == 200
    assert still.headers["content-type"].startswith("image/jpeg")
    page = client.get("/studio")
    assert page.status_code == 200
    assert "Color Grading" in page.text
    assert page.text.count('data-color-wheel="') == 3
    assert page.text.count('class="studio-color-wheel"') == 3
    assert 'id="inspector-image-section-color-wheels" class="studio-image-section" open' in page.text
    assert "data-color-wheels=" in page.text
    reset = client.patch(
        f"/api/studio/{clip_id}/color-wheels",
        json={"wheels": {key: {"x": 0, "y": 0} for key in WHEEL_IDS}},
    )
    assert reset.status_code == 200
    denied_again = client.get(f"/api/studio/{clip_id}/preview-frame")
    assert denied_again.status_code == 422


def test_color_wheels_javascript_pointer_math() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for pointer math regression")
    for script in ("tests/js/color_wheels.cjs", "tests/js/wheels_preview.cjs"):
        subprocess.run([node, script], check=True, timeout=20)


def test_color_wheels_preview_and_mp4_pixels_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg = _ffmpeg()
    data = tmp_path / "data"
    monkeypatch.setattr("orga_drone.config.settings", Settings(data_dir=data))
    video = tmp_path / "synthetic.mp4"
    _run(ffmpeg, "-f", "lavfi", "-i", "smptebars=s=320x180:r=30:d=1.5",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video))
    cube = tmp_path / "mild.cube"
    lines = ['TITLE "Mild channel mix"', "LUT_3D_SIZE 2"]
    for blue in (0, 1):
        for green in (0, 1):
            for red in (0, 1):
                lines.append(
                    f"{0.05 + red * 0.9} {0.04 + green * 0.9} {0.03 + blue * 0.9}"
                )
    cube.write_text("\n".join(lines) + "\n", encoding="utf-8")
    asset = import_lut_from_path(data, cube)
    look = ColorLook(creative_lut=asset, creative_strength=100)
    wheels = ColorWheels(
        shadows=ColorWheelPoint(x=0.5, y=-0.2),
        midtones=ColorWheelPoint(x=-0.2, y=0.6),
        highlights=ColorWheelPoint(x=0.1, y=-0.7),
    )
    clip = StudioExportClip(
        video, "video", 1.2, source_start_s=0.1, source_end_s=1.3,
        image=ImageAdjust(exposure=5),
        color_look=look,
        hsl=HslAdjust(blue=HslRange(hue=20, saturation=25)),
        color_wheels=wheels,
    )
    output = FfmpegStudioEncoder().render(
        StudioExportConfig(
            output_path=tmp_path / "export.mp4",
            width=320,
            height=180,
            clips=(clip,),
            quality="best",
        )
    )
    for local in (0.2, 0.8):
        still = render_preview_frame(
            PreviewFrameRequest(
                video, "video", 0.1 + local, clip.image, look,
                hsl=clip.hsl, color_wheels=wheels, max_edge=320,
            ),
            data_dir=data,
        )
        extracted = tmp_path / f"frame-{local}.png"
        _run(ffmpeg, "-ss", str(local), "-i", str(output), "-frames:v", "1",
             "-vf", "scale=in_color_matrix=bt709:in_range=tv,format=rgb24", str(extracted))
        with Image.open(still) as a, Image.open(extracted) as b:
            difference = ImageStat.Stat(ImageChops.difference(a.convert("RGB"), b.convert("RGB")))
            assert max(difference.mean) < 8, {"time": local, "error": difference.mean}
