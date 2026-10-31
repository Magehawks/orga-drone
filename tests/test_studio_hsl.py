"""Per-clip HSL colour mixer (Issue #232)."""

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
from orga_drone.export.studio_encoder import (
    _segment_vf_for_clip,
    FfmpegStudioEncoder,
)
from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.studio_hsl import (
    RANGE_IDS,
    HslAdjust,
    HslRange,
    apply_hsl_rgb,
    dump_hsl_adjust,
    ffmpeg_hsl_chain,
    hsl_adjust_from_effect_settings,
    hue_weights,
    parse_hsl_payload,
)
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


def test_neutral_mixer_is_identity_and_serializes_empty() -> None:
    hsl = HslAdjust()
    assert hsl.is_neutral
    assert apply_hsl_rgb(0.2, 0.5, 0.8, hsl) == (0.2, 0.5, 0.8)
    assert ffmpeg_hsl_chain(hsl, data_dir=Path("unused")) == ""
    for raw in (None, "", "{}", "{", "[]", '{"hsl":"nope"}', '{"hsl":{"ranges":[]}}'):
        assert hsl_adjust_from_effect_settings(raw).is_neutral
    blob = dump_hsl_adjust('{"image":{"exposure":10}}', HslAdjust())
    stored = json.loads(blob)
    assert stored["image"]["exposure"] == 10
    assert stored["hsl"]["ranges"]["red"] == {"hue": 0, "saturation": 0, "luminance": 0}


def test_hue_weights_are_smooth_and_sum_to_one() -> None:
    for hue in (0, 15, 30, 60, 90, 120, 180, 240, 270, 300, 330, 359.9):
        weights = hue_weights(hue)
        assert sum(weights) == pytest.approx(1.0)
        assert all(0.0 <= weight <= 1.0 for weight in weights)
    halfway = hue_weights(15)
    assert halfway[0] == pytest.approx(0.5)
    assert halfway[1] == pytest.approx(0.5)
    # A pixel just either side of a boundary stays continuous.
    left = hue_weights(29.999)
    right = hue_weights(30.001)
    assert max(abs(a - b) for a, b in zip(left, right)) < 0.001
    assert left[1] == pytest.approx(1.0, abs=0.001)
    assert right[1] == pytest.approx(1.0, abs=0.001)


def test_hue_saturation_luminance_and_independence() -> None:
    blue = HslAdjust(blue=HslRange(hue=20, saturation=40, luminance=-15))
    shifted = apply_hsl_rgb(0.0, 0.0, 1.0, blue)
    assert shifted[0] > 0.05  # blue moved toward violet (red channel rises)
    assert shifted[2] > 0.8
    # Green is a different range and stays unchanged by blue settings.
    assert apply_hsl_rgb(0.0, 1.0, 0.0, blue) == pytest.approx((0.0, 1.0, 0.0))
    desaturated = apply_hsl_rgb(0.0, 1.0, 0.0, HslAdjust(green=HslRange(saturation=-100)))
    assert desaturated[0] == pytest.approx(desaturated[1])
    assert desaturated[1] == pytest.approx(desaturated[2])
    darker = apply_hsl_rgb(0.0, 0.0, 1.0, HslAdjust(blue=HslRange(luminance=-100)))
    assert max(darker) < 1.0
    brighter = apply_hsl_rgb(0.0, 0.0, 1.0, HslAdjust(blue=HslRange(luminance=100)))
    assert brighter[0] > 0.0
    assert max(brighter) <= 1.0
    # Near-gray pixels have no defined hue and must not be tinted.
    assert apply_hsl_rgb(0.5, 0.5, 0.5, HslAdjust(red=HslRange(hue=100))) == (0.5, 0.5, 0.5)


def test_parse_patch_keeps_other_ranges_and_rejects_bad_values() -> None:
    current = HslAdjust(
        red=HslRange(hue=1),
        blue=HslRange(saturation=2),
    )
    updated = parse_hsl_payload({"range": "green", "hue": 12.4}, current)
    assert updated.red.hue == 1
    assert updated.blue.saturation == 2
    assert updated.green.hue == 12
    updated = parse_hsl_payload(
        {"ranges": {"blue": {"luminance": -30}}}, updated
    )
    assert updated.blue.saturation == 2
    assert updated.blue.luminance == -30
    with pytest.raises(ValueError, match="hue"):
        parse_hsl_payload({"range": "blue", "hue": 101}, current)
    with pytest.raises(ValueError, match="saturation"):
        parse_hsl_payload({"ranges": {"blue": {"saturation": True}}}, current)
    with pytest.raises(ValueError, match="colour range"):
        parse_hsl_payload({"range": "pink", "hue": 1}, current)
    with pytest.raises(ValueError, match="HSL"):
        parse_hsl_payload({"image": {}}, current)
    # Stored garbage reads as neutral instead of raising.
    corrupt = hsl_adjust_from_effect_settings(
        '{"hsl":{"ranges":{"blue":{"hue":900,"saturation":"x","luminance":true}}}}'
    )
    assert corrupt.blue == HslRange()


def test_settings_persist_per_clip_and_old_projects_load(tmp_path: Path) -> None:
    db = Database(tmp_path / "studio.sqlite3")
    media_id = _seed_media(
        db, tmp_path / "lib", filename="cloud.MP4", kind="video", duration_s=8.0
    )
    first = _add(db, media_id)
    second = _add(db, media_id)
    db.set_studio_hsl(first, {"ranges": {"blue": {"hue": 20, "luminance": -15}}})
    db.set_studio_hsl(second, {"ranges": {"green": {"saturation": -65}}})
    first_item = next(i for i in db.list_studio_items(1) if i.id == first)
    second_item = next(i for i in db.list_studio_items(1) if i.id == second)
    first_hsl = hsl_adjust_from_effect_settings(first_item.effect_settings)
    second_hsl = hsl_adjust_from_effect_settings(second_item.effect_settings)
    assert first_hsl.blue.hue == 20
    assert first_hsl.blue.luminance == -15
    assert second_hsl.green.saturation == -65
    assert first_hsl.green.is_neutral
    assert second_hsl.blue.is_neutral
    # Existing project blobs without hsl stay neutral and keep their image grade.
    with db.connect() as conn:
        conn.execute(
            "UPDATE studio_clips SET effect_settings = ? WHERE id = ?",
            ('{"image":{"exposure":12},"color":{"input_profile":"rec709"}}', second),
        )
    item = next(i for i in db.list_studio_items(1) if i.id == second)
    assert hsl_adjust_from_effect_settings(item.effect_settings).is_neutral
    assert "exposure" in str(item.effect_settings)


def test_export_chain_order_and_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setattr("orga_drone.config.settings", Settings(data_dir=data_dir))
    hsl = HslAdjust(blue=HslRange(hue=20, saturation=30, luminance=-15))
    chain = ffmpeg_hsl_chain(hsl, data_dir=data_dir)
    assert "lut3d=file=" in chain
    assert "hsl-luts" in chain
    assert list((data_dir / "hsl-luts").glob("*.cube"))
    clip = StudioExportClip(
        Path("clip.mp4"),
        "video",
        4.0,
        image=ImageAdjust(contrast=20),
        hsl=hsl,
    )
    vf = _segment_vf_for_clip(320, 180, clip)
    assert vf.index("eq=contrast=") < vf.index("lut3d=")
    assert vf.index("lut3d=") < vf.index("scale=")
    neutral = _segment_vf_for_clip(
        320, 180, StudioExportClip(Path("clip.mp4"), "video", 4.0)
    )
    assert "lut3d=" not in neutral


def test_hsl_combines_with_looks_and_luts_in_one_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setattr("orga_drone.config.settings", Settings(data_dir=data_dir))
    asset = import_lut_from_path(
        data_dir, write_identity_cube(tmp_path / "identity.cube")
    )
    look = ColorLook(creative_lut=asset, creative_strength=100)
    hsl = HslAdjust(blue=HslRange(hue=20))
    clip = StudioExportClip(
        Path("clip.mp4"),
        "video",
        4.0,
        image=ImageAdjust(exposure=10),
        color_look=look,
        hsl=hsl,
    )
    export_vf = _segment_vf_for_clip(320, 180, clip)
    assert export_vf.count("lut3d=") == 2
    first = export_vf.index("lut3d=")
    second = export_vf.index("lut3d=", first + 1)
    assert export_vf.index("exposure=") < first
    assert "hsl-luts" not in export_vf[first:second]
    assert "hsl-luts" in export_vf[second:]
    preview_vf = preview_filter_chain(
        clip.image, look, hsl=hsl, data_dir=data_dir, work_dir=tmp_path / "work"
    )
    assert preview_vf.count("lut3d=") == 2
    assert "hsl-luts" in preview_vf[preview_vf.index("lut3d=", preview_vf.index("lut3d=") + 1):]
    # Neutral HSL leaves the existing grade+LUT chain byte-for-byte equivalent.
    preview_plain = preview_filter_chain(
        clip.image, look, data_dir=data_dir, work_dir=tmp_path / "work"
    )
    assert preview_filter_chain(
        clip.image, look, hsl=HslAdjust(), data_dir=data_dir, work_dir=tmp_path / "work"
    ) == preview_plain


def test_hsl_preview_api_and_clip_switch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    item = db.get_media(media_id)
    assert item is not None
    clip_id, _ = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
    )
    client = TestClient(app)
    denied = client.get(f"/api/studio/{clip_id}/preview-frame")
    assert denied.status_code == 422
    saved = client.patch(
        f"/api/studio/{clip_id}/hsl",
        json={"ranges": {"blue": {"hue": 20, "saturation": 30, "luminance": -15}}},
    )
    assert saved.status_code == 200
    assert saved.json()["hsl"]["ranges"]["blue"]["hue"] == 20
    still = client.get(f"/api/studio/{clip_id}/preview-frame")
    assert still.status_code == 200
    assert still.headers["content-type"].startswith("image/jpeg")
    page = client.get("/studio")
    assert page.status_code == 200
    assert "HSL color mixer" in page.text or "HSL-Farbmischer" in page.text
    assert 'data-hsl=' in page.text
    assert 'id="inspector-image-section-hsl" class="studio-image-section" open' in page.text
    assert page.text.count("data-hsl-range=") == 8
    # Resetting all ranges returns the clip to the ordinary photo path.
    reset = client.patch(f"/api/studio/{clip_id}/hsl", json={"ranges": {
        key: {"hue": 0, "saturation": 0, "luminance": 0} for key in RANGE_IDS
    }})
    assert reset.status_code == 200
    denied_again = client.get(f"/api/studio/{clip_id}/preview-frame")
    assert denied_again.status_code == 422


def test_hsl_preview_javascript_lifecycle() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for browser lifecycle regression")
    subprocess.run([node, "tests/js/hsl_preview.cjs"], check=True, timeout=20)


def test_hsl_preview_and_mp4_pixels_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ffmpeg = _ffmpeg()
    data = tmp_path / "data"
    monkeypatch.setattr("orga_drone.config.settings", Settings(data_dir=data))
    video = tmp_path / "synthetic.mp4"
    # Six SMPTE bars keep red, green, blue and cyan present at once.
    _run(ffmpeg, "-f", "lavfi", "-i", "smptebars=s=320x180:r=30:d=1.5",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video))
    hsl = HslAdjust(
        green=HslRange(saturation=-65),
        blue=HslRange(hue=20, saturation=40, luminance=-15),
        magenta=HslRange(saturation=35),
    )
    clip = StudioExportClip(
        video, "video", 1.2, source_start_s=0.1, source_end_s=1.3, hsl=hsl
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
                video, "video", 0.1 + local, ImageAdjust(), ColorLook(),
                hsl=hsl, max_edge=320
            ),
            data_dir=data,
        )
        extracted = tmp_path / f"frame-{local}.png"
        _run(ffmpeg, "-ss", str(local), "-i", str(output), "-frames:v", "1",
             "-vf", "scale=in_color_matrix=bt709:in_range=tv,format=rgb24", str(extracted))
        with Image.open(still) as a, Image.open(extracted) as b:
            difference = ImageStat.Stat(
                ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
            )
            # JPEG + H.264 chroma/scaling tolerance. A different HSL path fails.
            assert max(difference.mean) < 8, {
                "time": local,
                "error": difference.mean,
            }
