"""Regression: Detail HSL must reach JPG/PNG export via the media export API.

The Photo Detail UI always posts ImageAdjust keys with the export body. The
export path must still apply persisted HSL/LUT/wheels from image_adjust_json
(preview/export parity). Source media must stay untouched.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orga_drone.app import create_app
from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.studio_hsl import HslAdjust, hsl_adjust_from_effect_settings


BLUE_RGB = (30, 60, 220)
RED_RGB = (220, 40, 40)


def _rgb_pixels(path: Path) -> list[tuple[int, int, int]]:
    with Image.open(path) as img:
        return list(img.convert("RGB").getdata())


def _mean_chroma(path: Path) -> float:
    pixels = _rgb_pixels(path)
    total = 0.0
    for r, g, b in pixels:
        mx = max(r, g, b)
        mn = min(r, g, b)
        total += (mx - mn) / 255.0
    return total / max(1, len(pixels))


def _blue_channel_mean(path: Path) -> float:
    pixels = _rgb_pixels(path)
    return sum(p[2] for p in pixels) / max(1, len(pixels))


@pytest.fixture
def photo_export_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prefs = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr("orga_drone.app_prefs.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_export.settings", prefs)
    monkeypatch.setattr("orga_drone.config.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_preview_frame.settings", prefs, raising=False)

    root = tmp_path / "lib"
    root.mkdir()
    media = root / "sky.jpg"
    Image.new("RGB", (120, 80), BLUE_RGB).save(media, format="JPEG", quality=95)
    source_sha = hashlib.sha256(media.read_bytes()).hexdigest()

    app = create_app()
    db: Database = app.state.db
    root_id = db.add_root(root, label="lib")
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": media.name,
            "path": str(media.resolve()),
            "size_bytes": media.stat().st_size,
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
    client = TestClient(app)
    return client, media_id, media.resolve(), source_sha, db


def _patch_blue_sat(client: TestClient, media_id: int, saturation: int) -> None:
    res = client.patch(
        f"/api/media/{media_id}/hsl",
        json={"ranges": {"blue": {"hue": 0, "saturation": saturation, "luminance": 0}}},
    )
    assert res.status_code == 200, res.text
    assert res.json()["hsl"]["ranges"]["blue"]["saturation"] == saturation


def _export_via_api(
    client: TestClient,
    media_id: int,
    dest: Path,
    *,
    still_format: str = "jpeg",
    include_image_adjust_keys: bool = True,
) -> Path:
    """Mirror Detail export: ImageAdjust keys are always present in the body."""
    body: dict = {
        "preset": "best",
        "output_path": str(dest),
        "overwrite": True,
        "still_format": still_format,
        "profile": "original",
    }
    if include_image_adjust_keys:
        # Same keys detail-export.js readAdjust() always posts.
        body.update(
            {
                "exposure": 0,
                "contrast": 0,
                "saturation": 0,
                "warmth": 0,
                "highlights": 0,
                "shadows": 0,
                "blacks": 0,
            }
        )
    res = client.post(f"/api/media/{media_id}/export", json=body)
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload.get("ok") and payload.get("job_id"), payload
    job_id = payload["job_id"]
    deadline = time.time() + 60
    while time.time() < deadline:
        status = client.get(f"/api/studio/export/jobs/{job_id}")
        assert status.status_code == 200, status.text
        job = status.json()
        state = job.get("state") or job.get("job", {}).get("state")
        if state in {"done", "completed", "success"}:
            break
        if state in {"failed", "cancelled", "error"}:
            raise AssertionError(f"export job failed: {job}")
        time.sleep(0.05)
    else:
        raise AssertionError("export job timed out")
    assert dest.is_file(), dest
    return dest


def test_api_export_applies_blue_saturation_minus_100_jpg_and_png(
    photo_export_client,
) -> None:
    client, media_id, source, source_sha, _db = photo_export_client
    out = source.parent.parent / "out"
    out.mkdir()

    neutral_jpg = out / "neutral.jpg"
    _export_via_api(client, media_id, neutral_jpg, still_format="jpeg")
    neutral_chroma = _mean_chroma(neutral_jpg)
    neutral_blue = _blue_channel_mean(neutral_jpg)

    _patch_blue_sat(client, media_id, -100)
    graded_jpg = out / "blue_sat_m100.jpg"
    _export_via_api(client, media_id, graded_jpg, still_format="jpeg")
    graded_chroma = _mean_chroma(graded_jpg)
    graded_blue = _blue_channel_mean(graded_jpg)

    # Desaturating blue must collapse chroma on a blue-dominant still.
    assert graded_chroma < neutral_chroma - 0.15
    assert abs(graded_blue - 128) < abs(neutral_blue - 128) or graded_chroma < 0.2

    graded_png = out / "blue_sat_m100.png"
    _export_via_api(client, media_id, graded_png, still_format="png")
    assert _mean_chroma(graded_png) < neutral_chroma - 0.15

    # Pixel-identical exports would mean HSL was ignored (the reported bug).
    assert hashlib.sha256(neutral_jpg.read_bytes()).hexdigest() != hashlib.sha256(
        graded_jpg.read_bytes()
    ).hexdigest()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha


def test_api_export_preview_parity_and_reopen_persistence(
    photo_export_client,
) -> None:
    client, media_id, source, source_sha, db = photo_export_client
    _patch_blue_sat(client, media_id, -100)

    preview = client.get(f"/api/media/{media_id}/color-preview?max_edge=120")
    assert preview.status_code == 200
    preview_path = source.parent.parent / "preview.jpg"
    preview_path.write_bytes(preview.content)
    preview_chroma = _mean_chroma(preview_path)

    out = source.parent.parent / "parity.jpg"
    _export_via_api(client, media_id, out, still_format="jpeg")
    export_chroma = _mean_chroma(out)
    # Same grade; allow JPEG/resolution tolerance.
    assert abs(export_chroma - preview_chroma) < 0.12
    assert export_chroma < 0.35

    # Persist across "reopen" (reload color API).
    reopened = client.get(f"/api/media/{media_id}/color")
    assert reopened.status_code == 200
    assert reopened.json()["hsl"]["ranges"]["blue"]["saturation"] == -100
    raw = db.get_image_adjust_json(source)
    assert hsl_adjust_from_effect_settings(raw).blue.saturation == -100
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha


def test_api_export_after_rapid_hsl_patches_uses_latest(
    photo_export_client,
) -> None:
    client, media_id, source, source_sha, _db = photo_export_client
    out = source.parent.parent / "rapid"
    out.mkdir()

    for sat in (0, -40, -80, -100):
        _patch_blue_sat(client, media_id, sat)
    dest = out / "latest.jpg"
    _export_via_api(client, media_id, dest, still_format="jpeg")
    assert _mean_chroma(dest) < 0.25
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha


def test_api_basic_image_adjust_export_still_works(
    photo_export_client,
) -> None:
    client, media_id, source, source_sha, _db = photo_export_client
    out = source.parent.parent / "basic"
    out.mkdir()
    # Brighten via ImageAdjust only (no HSL).
    save = client.post(
        f"/api/media/{media_id}/image-adjust",
        json={"exposure": 40, "contrast": 0, "saturation": 0, "warmth": 0},
    )
    assert save.status_code == 200, save.text
    bright = out / "bright.jpg"
    body = {
        "preset": "best",
        "output_path": str(bright),
        "overwrite": True,
        "still_format": "jpeg",
        "exposure": 40,
        "contrast": 0,
        "saturation": 0,
        "warmth": 0,
        "highlights": 0,
        "shadows": 0,
        "blacks": 0,
    }
    res = client.post(f"/api/media/{media_id}/export", json=body)
    assert res.status_code == 200, res.text
    job_id = res.json()["job_id"]
    deadline = time.time() + 60
    while time.time() < deadline:
        job = client.get(f"/api/studio/export/jobs/{job_id}").json()
        state = job.get("state") or job.get("job", {}).get("state")
        if state in {"done", "completed", "success"}:
            break
        if state in {"failed", "cancelled", "error"}:
            raise AssertionError(job)
        time.sleep(0.05)
    with Image.open(bright) as img:
        mean = sum(sum(p) for p in img.convert("RGB").getdata()) / (
            img.size[0] * img.size[1] * 3
        )
    assert mean > sum(BLUE_RGB) / 3 + 5
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha


def test_run_media_export_keeps_hsl_when_image_override_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Direct run_media_export path: payload ImageAdjust must not drop HSL."""
    from orga_drone.photo_color import merge_photo_hsl, merge_photo_image_adjust
    from orga_drone.studio_export import run_media_export
    from orga_drone.studio_hsl import HslRange
    from orga_drone.studio_image import ImageAdjust

    prefs = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr("orga_drone.app_prefs.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_export.settings", prefs)
    monkeypatch.setattr("orga_drone.config.settings", prefs)

    db = Database(tmp_path / "t.sqlite3")
    root = tmp_path / "lib"
    root.mkdir()
    photo = root / "blue.jpg"
    Image.new("RGB", (100, 60), BLUE_RGB).save(photo, format="JPEG", quality=95)
    before = hashlib.sha256(photo.read_bytes()).hexdigest()
    root_id = db.add_root(root, label="lib")
    mid = db.upsert_media(
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
    # Neutral baseline with ImageAdjust override present (Detail-shaped call).
    db.set_image_adjust_json(
        photo.resolve(),
        merge_photo_image_adjust(None, ImageAdjust(), look_id=""),
    )
    cleared = run_media_export(
        db,
        mid,
        preset="best",
        output_path=tmp_path / "cleared.jpg",
        image=ImageAdjust(),
        still_format="jpeg",
        overwrite=True,
    )
    raw = merge_photo_hsl(
        merge_photo_image_adjust(None, ImageAdjust(), look_id=""),
        HslAdjust(blue=HslRange(saturation=-100)),
    )
    db.set_image_adjust_json(photo.resolve(), raw)
    # Same call shape that previously dropped color_raw whenever image was set.
    graded = run_media_export(
        db,
        mid,
        preset="best",
        output_path=tmp_path / "g.jpg",
        image=ImageAdjust(),
        still_format="jpeg",
        overwrite=True,
    )
    assert _mean_chroma(graded) < _mean_chroma(cleared) - 0.15
    assert hashlib.sha256(photo.read_bytes()).hexdigest() == before
