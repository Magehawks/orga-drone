"""Local .cube LUT import and D-Log M conversion (Issue #174)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orga_drone.studio_lut import (
    ColorLook,
    LutInvalidError,
    LutMissingError,
    color_look_from_effect_settings,
    dump_color_look,
    escape_ffmpeg_lut_path,
    ffmpeg_lut_chain,
    import_lut_from_path,
    parse_color_look_payload,
    parse_cube_text,
    require_lut_asset,
    store_lut_asset,
    write_identity_cube,
    write_strength_blended_cube,
)


def test_identity_cube_validates_and_stores(tmp_path: Path) -> None:
    cube = write_identity_cube(tmp_path / "identity.cube", size=2)
    size, triples = parse_cube_text(cube.read_text(encoding="utf-8"))
    assert size == 2
    assert len(triples) == 8
    assert triples[0] == (0.0, 0.0, 0.0)
    assert triples[-1] == (1.0, 1.0, 1.0)
    name = import_lut_from_path(tmp_path / "data", cube)
    assert name.endswith(".cube")
    path = require_lut_asset(tmp_path / "data", name)
    assert path.is_file()


def test_invalid_cube_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.cube"
    bad.write_text("TITLE \"x\"\nLUT_3D_SIZE 2\n0 0 0\n", encoding="utf-8")
    with pytest.raises(LutInvalidError):
        store_lut_asset(tmp_path / "data", bad.read_bytes())


def test_dlog_requires_confirmation_and_lut() -> None:
    with pytest.raises(ValueError, match="confirmation"):
        parse_color_look_payload(
            {
                "input_profile": "dlog_m",
                "conversion_lut": "a" * 32 + ".cube",
                "conversion_confirmed": False,
            }
        )
    with pytest.raises(ValueError, match="\\.cube"):
        parse_color_look_payload(
            {
                "input_profile": "dlog_m",
                "conversion_lut": "",
                "conversion_confirmed": True,
            }
        )
    look = parse_color_look_payload(
        {
            "input_profile": "dlog_m",
            "conversion_lut": "a" * 32 + ".cube",
            "conversion_confirmed": True,
            "creative_strength": 80,
        }
    )
    assert look.input_profile == "dlog_m"
    assert look.conversion_confirmed is True
    assert look.creative_strength == 80


def test_color_look_roundtrip_preserves_unrelated_keys() -> None:
    existing = json.dumps({"image": {"exposure": 10}, "other": 1})
    look = ColorLook(
        input_profile="custom",
        creative_lut="b" * 32 + ".cube",
        creative_strength=50,
    )
    blob = dump_color_look(existing, look)
    data = json.loads(blob)
    assert data["image"]["exposure"] == 10
    assert data["other"] == 1
    restored = color_look_from_effect_settings(blob)
    assert restored.creative_lut == look.creative_lut
    assert restored.creative_strength == 50


def test_ffmpeg_lut_chain_missing_raises(tmp_path: Path) -> None:
    look = ColorLook(
        input_profile="dlog_m",
        conversion_lut="c" * 32 + ".cube",
        conversion_confirmed=True,
    )
    with pytest.raises(LutMissingError):
        ffmpeg_lut_chain(look, data_dir=tmp_path / "data")


def test_ffmpeg_lut_chain_applies_conversion_and_strength(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    cube = write_identity_cube(tmp_path / "id.cube", size=2)
    conversion = import_lut_from_path(data_dir, cube)
    creative = import_lut_from_path(data_dir, cube)
    look = ColorLook(
        input_profile="dlog_m",
        conversion_lut=conversion,
        conversion_confirmed=True,
        creative_lut=creative,
        creative_strength=50,
    )
    work = tmp_path / "work"
    chain = ffmpeg_lut_chain(look, data_dir=data_dir, work_dir=work)
    assert chain.count("lut3d=file=") == 2
    assert "interp=tetrahedral" in chain
    blended = work / f"creative_{creative}"
    assert blended.is_file()
    size, triples = parse_cube_text(blended.read_text(encoding="utf-8"))
    assert size == 2
    # Midpoint of identity stays identity when strength-blended with identity.
    assert triples[0] == pytest.approx((0.0, 0.0, 0.0))
    escaped = escape_ffmpeg_lut_path(require_lut_asset(data_dir, conversion))
    assert "lut3d=file=" in f"lut3d=file={escaped}"
    assert "\\" not in escaped.replace("\\:", "")
    assert "'" not in escaped


def test_color_api_requires_confirm_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from orga_drone.app import create_app
    from orga_drone.config import Settings
    from orga_drone.db import Database, make_identity_key

    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    app = create_app()
    db: Database = app.state.db
    root = tmp_path / "media"
    root.mkdir()
    root_id = db.add_root(root, label="t")
    video = root / "clip.MP4"
    video.write_bytes(b"video")
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": video.name,
            "path": str(video.resolve()),
            "size_bytes": 5,
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
    cube = write_identity_cube(tmp_path / "id.cube")
    imported = client.post("/api/studio/luts", json={"path": str(cube)})
    assert imported.status_code == 200
    asset = imported.json()["asset_name"]
    denied = client.patch(
        f"/api/studio/{clip_id}/color",
        json={
            "input_profile": "dlog_m",
            "conversion_lut": asset,
            "conversion_confirmed": False,
        },
    )
    assert denied.status_code == 400
    ok = client.patch(
        f"/api/studio/{clip_id}/color",
        json={
            "input_profile": "dlog_m",
            "conversion_lut": asset,
            "conversion_confirmed": True,
            "creative_lut": "",
            "creative_strength": 100,
        },
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["ok"] is True
    assert body["color_look"]["conversion_confirmed"] is True
    page = client.get("/studio")
    assert page.status_code == 200
    assert "Convert D-Log M" in page.text or "D-Log M umwandeln" in page.text
    assert "data-color-look=" in page.text


def test_strength_blend_moves_toward_identity(tmp_path: Path) -> None:
    source = tmp_path / "boost.cube"
    source.write_text(
        "\n".join(
            [
                'TITLE "boost"',
                "LUT_3D_SIZE 2",
                "0.2 0.0 0.0",
                "1.0 0.0 0.0",
                "0.0 1.0 0.0",
                "1.0 1.0 0.0",
                "0.0 0.0 1.0",
                "1.0 0.0 1.0",
                "0.0 1.0 1.0",
                "1.0 1.0 1.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    dest = tmp_path / "half.cube"
    write_strength_blended_cube(source, strength=50, destination=dest)
    _, triples = parse_cube_text(dest.read_text(encoding="utf-8"))
    assert triples[0] == pytest.approx((0.1, 0.0, 0.0))
