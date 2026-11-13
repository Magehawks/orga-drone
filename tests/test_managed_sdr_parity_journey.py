"""Managed-SDR Color Workspace numerical parity journey (#365 slice).

API-driven: convert → primaries → curves → wheels/HSL → pointwise preview
stability → bake.cube → spatial selection preview delta → CPU applicator delta.
Packaged WebView2 UI steps remain NOT_RUN.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.studio_grade_persistence import startup_backup_if_needed
from orga_drone.studio_managed_apply import apply_managed_grade_image


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    startup_backup_if_needed(tmp_path / "data", app_version="managed-parity")
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def _seed(db: Database, root: Path) -> int:
    root.mkdir(parents=True, exist_ok=True)
    photo = root / "sdr.jpg"
    Image.new("RGB", (64, 48), (40, 120, 200)).save(photo, format="JPEG", quality=95)
    root_id = db.add_root(root, label="parity")
    mid = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": photo.name,
            "path": str(photo.resolve()),
            "size_bytes": photo.stat().st_size,
            "duration_s": None,
            "recorded_at": "2024-06-01T12:00:00",
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
    item = db.get_media(mid)
    assert item is not None
    project = db.create_studio_project("Managed SDR parity")
    clip_id, _ = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
        project_id=project.id,
        source_media_id=mid,
    )
    return clip_id


def test_managed_sdr_api_parity_journey(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed(db, tmp_path / "lib")

    assert client.post(f"/api/studio/{clip_id}/grade/wrap").status_code == 200
    convert = client.post(
        f"/api/studio/{clip_id}/grade/convert-managed",
        json={"acknowledge_appearance_change": True},
    )
    assert convert.status_code == 200, convert.text
    current = client.get(f"/api/studio/{clip_id}/grade").json()
    rev = int(current["revision"])
    grade = current["grade"]
    assert grade["evaluator"] == "managed-sdr-v1"

    grade["steps"] = [
        {
            "id": "p1",
            "type": "primaries-v1",
            "enabled": True,
            "mix": 1,
            "selection_id": None,
            "params": {
                "exposure": 0.25,
                "kelvin": 5600,
                "tint": 5,
                "contrast": 1.05,
                "pivot": 0.18,
                "saturation": 1.1,
                "blacks": 0,
                "shadows": 0.02,
                "highlights": -0.05,
                "whites": 0,
            },
        },
        {
            "id": "c1",
            "type": "rgb-curves-v1",
            "enabled": True,
            "mix": 1,
            "selection_id": None,
            "params": {
                "domain": "linear-bt709",
                "master": [[0, 0], [0.5, 0.55], [1, 1]],
            },
        },
        {
            "id": "w1",
            "type": "wheels-v1",
            "enabled": True,
            "mix": 1,
            "selection_id": None,
            "params": {"lift": 0.02, "gamma": 1.0, "gain": 1.05, "offset": 0},
        },
        {
            "id": "h1",
            "type": "managed-hsl-v1",
            "enabled": True,
            "mix": 1,
            "selection_id": None,
            "params": {"hue": 8, "saturation": 0.1, "lightness": 0},
        },
    ]
    grade["selections"] = []
    put = client.put(
        f"/api/studio/{clip_id}/grade",
        json={"grade": grade, "expected_revision": rev},
    )
    assert put.status_code == 200, put.text
    rev = int(put.json()["revision"])

    still = client.get(
        f"/api/studio/{clip_id}/preview-frame",
        params={"t_s": 0, "expected_revision": rev},
    )
    assert still.status_code == 200, still.text
    assert still.headers.get("X-Orga-Grade-Revision") == str(rev)
    still2 = client.get(
        f"/api/studio/{clip_id}/preview-frame",
        params={"t_s": 0, "expected_revision": rev},
    )
    assert still2.status_code == 200
    assert still2.content == still.content

    bake = client.get(f"/api/studio/{clip_id}/grade/bake.cube", params={"rev": rev})
    assert bake.status_code == 200, bake.text
    assert "LUT_3D_SIZE" in bake.text

    preview_path = tmp_path / "preview.jpg"
    preview_path.write_bytes(still.content)
    preview = Image.open(preview_path).convert("RGB")

    graded = client.get(f"/api/studio/{clip_id}/grade").json()["grade"]
    spatial = dict(graded)
    spatial["steps"] = [{**spatial["steps"][0], "selection_id": "sel-1"}, *spatial["steps"][1:]]
    spatial["selections"] = [
        {
            "id": "sel-1",
            "mask": {
                "combine": "union",
                "leaves": [
                    {
                        "type": "radial",
                        "center": [0.5, 0.5],
                        "axes": [0.35, 0.35],
                        "feather": 0.1,
                    }
                ],
            },
            "qualifier": {"type": "luma", "inner": 0.35, "outer": 0.2},
            "invert": False,
        }
    ]
    spatial_put = client.put(
        f"/api/studio/{clip_id}/grade",
        json={"grade": spatial, "expected_revision": rev},
    )
    assert spatial_put.status_code == 200, spatial_put.text
    spatial_rev = int(spatial_put.json()["revision"])
    spatial_still = client.get(
        f"/api/studio/{clip_id}/preview-frame",
        params={"t_s": 0, "expected_revision": spatial_rev},
    )
    assert spatial_still.status_code == 200, spatial_still.text
    spatial_path = tmp_path / "spatial.jpg"
    spatial_path.write_bytes(spatial_still.content)
    spatial_preview = Image.open(spatial_path).convert("RGB")
    assert spatial_preview.size == preview.size
    diff = sum(
        abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])
        for a, b in zip(preview.getdata(), spatial_preview.getdata(), strict=True)
    )
    assert diff > 0, "spatial selection should change preview pixels"

    synth = [[(0.2, 0.4, 0.7) for _ in range(8)] for _ in range(6)]
    cpu = apply_managed_grade_image(synth, graded, lattice_domain="encoded-bt709")
    mean_abs = sum(
        abs(cpu[y][x][c] - synth[y][x][c])
        for y in range(6)
        for x in range(8)
        for c in range(3)
    ) / (6 * 8 * 3)
    assert mean_abs > 0.0

    reopen = client.get(f"/api/studio/{clip_id}/grade").json()
    assert reopen["revision"] == spatial_rev
    evidence = {
        "status": "PASS",
        "pointwise_preview_stable": True,
        "spatial_preview_diff_rgb_sum": diff,
        "cpu_synth_mean_abs_delta": mean_abs,
        "revision": spatial_rev,
        "packaged_webview2": "NOT_RUN",
    }
    (tmp_path / "managed_sdr_parity_evidence.json").write_text(
        json.dumps(evidence, indent=2), encoding="utf-8"
    )
