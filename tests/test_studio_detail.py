"""Studio sharpen and denoise (Issue #177)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.app import create_app
from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.export.studio_config import StudioExportClip
from orga_drone.export.studio_encoder import _segment_vf_for_clip
from orga_drone.studio_detail import (
    DetailEnhance,
    detail_from_effect_settings,
    ffmpeg_detail_chain,
    parse_detail_patch,
)
from orga_drone.studio_image import ImageAdjust


def test_detail_defaults_off_and_ffmpeg_order() -> None:
    assert DetailEnhance().is_neutral
    assert ffmpeg_detail_chain(DetailEnhance()) == ""
    chain = ffmpeg_detail_chain(DetailEnhance(sharpen=50, denoise=40))
    assert chain.startswith("unsharp=")
    assert "hqdn3d=" in chain
    assert chain.index("unsharp=") < chain.index("hqdn3d=")
    assert ";" not in chain
    with pytest.raises(ValueError):
        parse_detail_patch({"sharpen": 101}, DetailEnhance())
    graded = StudioExportClip(
        source_path=Path("clip.mp4"),
        kind="video",
        duration_s=2.0,
        image=ImageAdjust(contrast=20),
        detail=DetailEnhance(sharpen=100),
    )
    vf = _segment_vf_for_clip(1280, 720, graded)
    assert vf.index("eq=") < vf.index("unsharp=")
    assert vf.index("unsharp=") < vf.index("scale=")


def test_detail_api_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    app = create_app()
    db: Database = app.state.db
    root = tmp_path / "lib"
    root.mkdir()
    root_id = db.add_root(root, label="t")
    video = root / "v.MP4"
    video.write_bytes(b"vid")
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": video.name,
            "path": str(video.resolve()),
            "size_bytes": 3,
            "duration_s": 2.0,
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
    page = client.get("/studio")
    assert 'id="inspector-detail-sharpen"' in page.text
    assert 'id="inspector-detail-denoise"' in page.text
    bad = client.patch(f"/api/studio/{clip_id}/detail", json={"sharpen": -1})
    assert bad.status_code == 400
    ok = client.patch(
        f"/api/studio/{clip_id}/detail", json={"sharpen": 35, "denoise": 20}
    )
    assert ok.status_code == 200
    assert ok.json()["detail"] == {"sharpen": 35, "denoise": 20}
    stored = {row.id: row for row in db.list_studio_items()}[clip_id]
    assert detail_from_effect_settings(stored.effect_settings).as_dict() == {
        "sharpen": 35,
        "denoise": 20,
    }
