"""Managed bake.cube endpoint for WebGL adapter (#360)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def _grade(spatial: bool = False) -> dict:
    selection_id = "sel-1" if spatial else None
    grade = {
        "schema_version": 1,
        "evaluator": "managed-sdr-v1",
        "revision": 1,
        "input": {"profile": "bt709-sdr", "technical_lut": None},
        "working": "linear-bt709",
        "steps": [
            {
                "id": "p1",
                "type": "primaries-v1",
                "enabled": True,
                "mix": 1,
                "selection_id": selection_id,
                "params": {
                    "exposure": 0.2,
                    "kelvin": 6500,
                    "tint": 0,
                    "contrast": 1,
                    "pivot": 0.18,
                    "saturation": 1,
                    "blacks": 0,
                    "shadows": 0,
                    "highlights": 0,
                    "whites": 0,
                },
            }
        ],
        "selections": (
            [
                {
                    "id": "sel-1",
                    "mask": {
                        "combine": "union",
                        "leaves": [
                            {
                                "type": "radial",
                                "center": [0.5, 0.5],
                                "axes": [0.2, 0.2],
                                "feather": 0,
                            }
                        ],
                    },
                    "invert": False,
                }
            ]
            if spatial
            else []
        ),
        "animation": [],
        "output": {"profile": "bt709-sdr", "gamut": "clip"},
        "extensions": {},
    }
    return grade


def _seed_photo(db: Database, root: Path) -> int:
    root.mkdir(parents=True, exist_ok=True)
    photo = root / "a.jpg"
    Image.new("RGB", (32, 32), (180, 40, 40)).save(photo, format="JPEG", quality=90)
    root_id = db.add_root(root, label="gpu")
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
            "sequence": 1,
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
    return clip_id


def test_bake_cube_pointwise_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed_photo(db, tmp_path / "lib")
    grade = _grade(spatial=False)
    put = client.put(
        f"/api/studio/{clip_id}/grade",
        json={"grade": grade, "expected_revision": 0},
    )
    # Fresh managed write may require convert path; if put fails, wrap+convert.
    if put.status_code >= 400:
        client.post(f"/api/studio/{clip_id}/grade/wrap")
        client.post(
            f"/api/studio/{clip_id}/grade/convert-managed",
            json={"acknowledge_appearance_change": True},
        )
        get = client.get(f"/api/studio/{clip_id}/grade")
        rev = get.json()["revision"]
        put = client.put(
            f"/api/studio/{clip_id}/grade",
            json={"grade": grade, "expected_revision": rev},
        )
    assert put.status_code < 400, put.text
    rev = put.json()["revision"]
    response = client.get(f"/api/studio/{clip_id}/grade/bake.cube?rev={rev}")
    assert response.status_code == 200
    assert "LUT_3D_SIZE" in response.text


def test_bake_cube_spatial_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed_photo(db, tmp_path / "lib")
    grade = _grade(spatial=True)
    put = client.put(
        f"/api/studio/{clip_id}/grade",
        json={"grade": grade, "expected_revision": 0},
    )
    if put.status_code >= 400:
        client.post(f"/api/studio/{clip_id}/grade/wrap")
        client.post(
            f"/api/studio/{clip_id}/grade/convert-managed",
            json={"acknowledge_appearance_change": True},
        )
        get = client.get(f"/api/studio/{clip_id}/grade")
        rev = get.json()["revision"]
        put = client.put(
            f"/api/studio/{clip_id}/grade",
            json={"grade": grade, "expected_revision": rev},
        )
    assert put.status_code < 400, put.text
    response = client.get(f"/api/studio/{clip_id}/grade/bake.cube")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "UNSUPPORTED_GRADE"
