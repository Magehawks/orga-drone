"""Studio pause/scrub stills reuse export grade+LUT builders (ADR 0028 / #211)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.local_cache import clear_regenerable_cache
from orga_drone.studio_image import ImageAdjust, ffmpeg_grade_chain
from orga_drone.studio_lut import ColorLook, import_lut_from_path, write_identity_cube
from orga_drone.studio_preview_frame import (
    PREVIEW_STILLS_DIR,
    PreviewFrameRequest,
    cache_key_for,
    look_needs_preview_still,
    preview_filter_chain,
    quantize_preview_time,
    render_preview_frame,
)


def _ffmpeg() -> str:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    return ffmpeg


def _make_photo(path: Path, *, color: str = "0x4060A0") -> Path:
    ffmpeg = _ffmpeg()
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=320x180:d=0.1",
        "-frames:v",
        "1",
        str(path),
    ]
    subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **subprocess_no_window_kwargs(),
    )
    return path


def _make_video(path: Path) -> Path:
    ffmpeg = _ffmpeg()
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=0x306090:s=320x180:d=1",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-t",
        "1",
        str(path),
    ]
    subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **subprocess_no_window_kwargs(),
    )
    return path


def _red_boost_cube(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                'TITLE "red boost"',
                "LUT_3D_SIZE 2",
                "0.0 0.0 0.0",
                "1.0 0.0 0.0",
                "0.0 1.0 0.0",
                "1.0 1.0 0.0",
                "0.0 0.0 1.0",
                "1.0 0.0 1.0",
                "0.0 1.0 1.0",
                "1.0 0.2 0.2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_quantize_and_look_gate() -> None:
    assert quantize_preview_time(1.24) == pytest.approx(1.2)
    assert look_needs_preview_still(ColorLook()) is False
    assert look_needs_preview_still(
        ColorLook(input_profile="custom")
    ) is False
    assert look_needs_preview_still(
        ColorLook(
            input_profile="dlog_m",
            conversion_lut="a" * 32 + ".cube",
            conversion_confirmed=False,
        )
    ) is False
    assert look_needs_preview_still(
        ColorLook(creative_lut="a" * 32 + ".cube", creative_strength=50)
    )
    assert look_needs_preview_still(
        ColorLook(
            input_profile="dlog_m",
            conversion_lut="a" * 32 + ".cube",
            conversion_confirmed=True,
        )
    )


def test_preview_filter_reuses_grade_and_lut_builders(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    cube = write_identity_cube(tmp_path / "id.cube")
    asset = import_lut_from_path(data_dir, cube)
    image = ImageAdjust(exposure=10, contrast=5)
    look = ColorLook(creative_lut=asset, creative_strength=100)
    chain = preview_filter_chain(
        image, look, data_dir=data_dir, work_dir=tmp_path / "work"
    )
    grade = ffmpeg_grade_chain(image)
    assert grade
    assert chain.startswith(grade + ",")
    assert "lut3d=file=" in chain
    assert "scale=720:720:force_original_aspect_ratio=decrease" in chain


def test_render_preview_frame_caches_jpeg(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    photo = _make_photo(tmp_path / "still.jpg")
    asset = import_lut_from_path(data_dir, _red_boost_cube(tmp_path / "boost.cube"))
    req = PreviewFrameRequest(
        media_path=photo,
        kind="photo",
        source_time_s=0.0,
        image=ImageAdjust(warmth=20),
        look=ColorLook(creative_lut=asset, creative_strength=100),
    )
    first = render_preview_frame(req, data_dir=data_dir)
    second = render_preview_frame(req, data_dir=data_dir)
    assert first == second
    assert first.suffix == ".jpg"
    assert first.stat().st_size > 100
    assert (data_dir / PREVIEW_STILLS_DIR).is_dir()


def test_cache_key_stable_for_same_inputs(tmp_path: Path) -> None:
    photo = _make_photo(tmp_path / "a.jpg")
    st = photo.stat()
    req = PreviewFrameRequest(
        media_path=photo,
        kind="photo",
        source_time_s=0.12,
        image=ImageAdjust(exposure=1),
        look=ColorLook(),
    )
    a = cache_key_for(req, media_mtime_ns=st.st_mtime_ns, media_size=st.st_size)
    b = cache_key_for(req, media_mtime_ns=st.st_mtime_ns, media_size=st.st_size)
    assert a == b
    other = PreviewFrameRequest(
        media_path=photo,
        kind="photo",
        source_time_s=0.12,
        image=ImageAdjust(exposure=2),
        look=ColorLook(),
    )
    assert cache_key_for(other, media_mtime_ns=st.st_mtime_ns, media_size=st.st_size) != a


def test_preview_frame_api_and_cache_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orga_drone.app import create_app
    from orga_drone.config import Settings
    from orga_drone.db import Database, make_identity_key

    data_dir = tmp_path / "data"
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=data_dir))
    app = create_app()
    db: Database = app.state.db
    root = tmp_path / "media"
    root.mkdir()
    root_id = db.add_root(root, label="t")
    video = _make_video(root / "clip.MP4")
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": video.name,
            "path": str(video.resolve()),
            "size_bytes": video.stat().st_size,
            "duration_s": 1.0,
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
    denied = client.get(f"/api/studio/{clip_id}/preview-frame?t_s=0.2")
    assert denied.status_code == 422
    cube = _red_boost_cube(tmp_path / "boost.cube")
    imported = client.post("/api/studio/luts", json={"path": str(cube)})
    assert imported.status_code == 200
    asset = imported.json()["asset_name"]
    colored = client.patch(
        f"/api/studio/{clip_id}/color",
        json={
            "input_profile": "custom",
            "creative_lut": asset,
            "creative_strength": 100,
            "conversion_lut": "",
            "conversion_confirmed": False,
        },
    )
    assert colored.status_code == 200
    still = client.get(f"/api/studio/{clip_id}/preview-frame?t_s=0.25")
    assert still.status_code == 200
    assert still.headers["content-type"].startswith("image/jpeg")
    assert still.headers.get("x-orga-preview-still") == "1"
    assert still.headers["cache-control"] == "no-store"
    assert len(still.content) > 100
    cached = list((data_dir / PREVIEW_STILLS_DIR).glob("*.jpg"))
    assert cached
    page = client.get("/studio")
    assert page.status_code == 200
    assert "studio-preview-lut-still" in page.text
    assert "Still frame with color file" in page.text or "Standbild mit Farbdatei" in page.text
    assert "rendered still" in page.text.lower() or "berechnetes Standbild" in page.text
    removed = clear_regenerable_cache(data_dir)
    assert removed >= len(still.content)
    assert not list((data_dir / PREVIEW_STILLS_DIR).glob("*.jpg"))
    assert (data_dir / PREVIEW_STILLS_DIR).is_dir()


def test_missing_lut_returns_actionable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orga_drone.app import create_app
    from orga_drone.config import Settings
    from orga_drone.db import make_identity_key
    from orga_drone.studio_lut import dump_color_look

    data_dir = tmp_path / "data"
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=data_dir))
    app = create_app()
    db = app.state.db
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
    look = ColorLook(creative_lut="f" * 32 + ".cube", creative_strength=100)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT effect_settings FROM studio_clips WHERE id = ?",
            (clip_id,),
        ).fetchone()
        blob = dump_color_look(str(row["effect_settings"] or "{}"), look)
        conn.execute(
            "UPDATE studio_clips SET effect_settings = ? WHERE id = ?",
            (blob, clip_id),
        )
    client = TestClient(app)
    res = client.get(f"/api/studio/{clip_id}/preview-frame")
    assert res.status_code == 409
    assert "missing" in res.json()["detail"].lower()
