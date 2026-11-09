"""Read-only Before inputs, technical conversion, cache and export safety (#322)."""
from __future__ import annotations

import hashlib
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orga_drone.app import create_app
from orga_drone.config import Settings
from orga_drone.export.studio_config import StudioExportClip, StudioExportConfig
from orga_drone.export.studio_encoder import FfmpegStudioEncoder
from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.studio_color_wheels import ColorWheelPoint, ColorWheels
from orga_drone.studio_hsl import HslAdjust, HslRange
from orga_drone.studio_image import ImageAdjust
from orga_drone.studio_lut import ColorLook, import_lut_from_path
from orga_drone.studio_preview_frame import (
    PreviewFrameRequest, before_color_request, cache_key_for, render_preview_frame,
)


def test_before_inputs_preserve_technical_conversion_and_existing_cache_contract(tmp_path: Path) -> None:
    req = PreviewFrameRequest(tmp_path / "a.jpg", "photo", 0, ImageAdjust(exposure=30),
                              ColorLook("dlog_m", "technical.cube", "creative.cube", 65, True),
                              hsl=HslAdjust(blue=HslRange(hue=20)),
                              color_wheels=ColorWheels(shadows=ColorWheelPoint(.2, .1)),
                              saturation=.3, detail=True)
    before = before_color_request(req)
    assert before.image.is_neutral and before.hsl.is_neutral and before.color_wheels.is_neutral
    assert before.saturation == 1 and not before.detail
    assert before.look == ColorLook(input_profile="dlog_m", conversion_lut="technical.cube",
                                    conversion_confirmed=True)
    assert req.look.creative_lut == "creative.cube" and req.image.exposure == 30
    neutral = replace(req, image=ImageAdjust(), hsl=HslAdjust(), color_wheels=ColorWheels(),
                      look=before.look, saturation=1.0, detail=False)
    def key(r: PreviewFrameRequest) -> str:
        return cache_key_for(r, media_mtime_ns=1, media_size=2)
    assert key(before) == key(neutral) != key(req)
    unconfirmed = before_color_request(replace(req, look=replace(req.look, conversion_confirmed=False)))
    assert not unconfirmed.look.conversion_lut and not unconfirmed.look.creative_lut


@pytest.mark.parametrize("extension", ["jpg", "png", "mp4"])
def test_before_route_is_read_only_and_preserves_technical_pixels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extension: str,
) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg unavailable")
    settings = Settings(data_dir=tmp_path / "data")
    for module in ("orga_drone.app", "orga_drone.config", "orga_drone.studio_export"):
        monkeypatch.setattr(module + ".settings", settings)
    app = create_app()
    db = app.state.db
    source = tmp_path / ("synthetic." + extension)
    kind = "video" if extension == "mp4" else "photo"
    if kind == "video":
        subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
                        "color=c=0x406080:s=320x180:r=30:d=1", "-pix_fmt", "yuv420p", str(source)],
                       check=True, capture_output=True, timeout=30, **subprocess_no_window_kwargs())
    else:
        Image.new("RGB", (320, 180), (64, 96, 128)).save(source)
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    root = db.add_root(tmp_path, label="Synthetic")
    mid = db.upsert_media(dict(root_id=root, kind=kind, filename=source.name, path=str(source),
                               size_bytes=source.stat().st_size, duration_s=1 if kind == "video" else None,
                               width=320, height=180, has_srt=0, has_lrf=0))
    cid, _ = db.add_studio_item(str(source), identity_key="synthetic", filename=source.name,
                               recorded_at=None, kind=kind, source_media_id=mid)
    cube = tmp_path / "technical.cube"
    cube.write_text('LUT_3D_SIZE 2\n' + "\n".join(
        f"{r * .7 + .15} {g * .8} {b * .65}" for b in (0, 1) for g in (0, 1) for r in (0, 1)
    ) + "\n")
    technical = import_lut_from_path(settings.data_dir, cube)
    cube.write_text(cube.read_text().replace("0.15", "0.25"))
    creative = import_lut_from_path(settings.data_dir, cube)
    look = ColorLook("dlog_m", technical, creative, 70, True)
    db.set_studio_color_look(cid, look.as_dict())
    db.set_studio_image_adjust(cid, {"exposure": 30, "contrast": 15, "saturation": -20})
    db.set_studio_hsl(cid, {"range": "blue", "hue": 20})
    db.set_studio_color_wheels(cid, {"wheel": "shadows", "x": .2, "y": .1})
    client = TestClient(app)
    def snapshot() -> list[list[tuple[object, ...]]]:
        with db.connect() as conn:
            tables = [str(r[0]) for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return [[tuple(row) for row in conn.execute(f'SELECT * FROM "{table}"')]
                    for table in tables]
    saved = snapshot()
    normal = client.get(f"/api/studio/{cid}/preview-frame?t_s=0.2")
    assert normal.status_code == 200
    before = client.get(f"/api/studio/{cid}/preview-frame?t_s=0.2&before=1")
    assert before.status_code == 200
    reference = render_preview_frame(PreviewFrameRequest(
        source, kind, .2 if kind == "video" else 0, ImageAdjust(),
        ColorLook(input_profile="dlog_m", conversion_lut=technical, conversion_confirmed=True),
    ), data_dir=settings.data_dir)
    assert before.content == reference.read_bytes() != normal.content
    assert client.get(f"/api/studio/{cid}/preview-frame?t_s=0.2").content == normal.content
    assert snapshot() == saved, "comparison must not write project, history or media tables"
    # Actual encoder output stays byte-identical around repeated comparison GETs.
    clip = StudioExportClip(source, kind, .5, image=ImageAdjust(exposure=30), color_look=look)
    first = FfmpegStudioEncoder().render(StudioExportConfig(tmp_path / "first.mp4", 320, 180, clips=(clip,)))
    for _ in range(4):
        assert client.get(f"/api/studio/{cid}/preview-frame?before=1&t_s=0.2").content == before.content
    second = FfmpegStudioEncoder().render(StudioExportConfig(tmp_path / "second.mp4", 320, 180, clips=(clip,)))
    assert first.read_bytes() == second.read_bytes()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original
    # Missing creative files must not affect Before, but a missing technical LUT must fail.
    (settings.data_dir / "luts" / creative).unlink()
    assert client.get(f"/api/studio/{cid}/preview-frame?before=1&t_s=0.2").status_code == 200
    assert client.get(f"/api/studio/{cid}/preview-frame?t_s=0.2").status_code == 409
    (settings.data_dir / "luts" / technical).unlink()
    assert client.get(f"/api/studio/{cid}/preview-frame?before=1&t_s=0.2").status_code == 409
