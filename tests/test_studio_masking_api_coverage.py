"""HTTP + persistence coverage for mask / object-select workflows (#542)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.studio_grade_persistence import startup_backup_if_needed


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    prefs = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr("orga_drone.app_prefs.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_export.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_clip_still.settings", prefs)
    monkeypatch.setattr("orga_drone.config.settings", prefs)
    monkeypatch.setattr("orga_drone.app.settings", prefs)
    startup_backup_if_needed(tmp_path / "data", app_version="mask-api")
    return prefs


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    _isolate(monkeypatch, tmp_path)
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def _seed_photo(db: Database, root: Path) -> int:
    root.mkdir(parents=True, exist_ok=True)
    photo = root / "blob.jpg"
    img = Image.new("RGB", (200, 200), (40, 40, 40))
    draw = ImageDraw.Draw(img)
    draw.ellipse((40, 40, 160, 160), fill=(40, 180, 60))
    img.save(photo, quality=95)
    root_id = db.add_root(root, label="mask-api")
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
    project = db.create_studio_project("Mask API")
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


def _ensure_managed(client: TestClient, clip_id: int) -> dict:
    current = client.get(f"/api/studio/{clip_id}/grade").json()
    if current.get("evaluator") != "managed-sdr-v1":
        assert client.post(f"/api/studio/{clip_id}/grade/wrap").status_code == 200
        assert (
            client.post(
                f"/api/studio/{clip_id}/grade/convert-managed",
                json={"acknowledge_appearance_change": True},
            ).status_code
            == 200
        )
        current = client.get(f"/api/studio/{clip_id}/grade").json()
    assert current["evaluator"] == "managed-sdr-v1"
    return current


def test_object_select_http_single_and_multiseed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed_photo(db, tmp_path / "lib")
    grade = _ensure_managed(client, clip_id)
    rev = int(grade["revision"])

    bad = client.post(
        f"/api/studio/{clip_id}/grade/object-select",
        json={"u": -0.1, "v": 0.5, "expected_revision": rev},
    )
    assert bad.status_code == 400

    single = client.post(
        f"/api/studio/{clip_id}/grade/object-select",
        json={"u": 0.5, "v": 0.5, "expected_revision": rev, "expand_passes": 0},
    )
    assert single.status_code == 200, single.text
    body = single.json()
    assert body["ok"] is True
    assert len(body["proposal"]["points"]) >= 3
    assert body["proposal"]["seeds_uv"]

    multi = client.post(
        f"/api/studio/{clip_id}/grade/object-select",
        json={
            "u": 0.5,
            "v": 0.5,
            "seeds": [[0.55, 0.55], [0.45, 0.45]],
            "expected_revision": rev,
            "expand_passes": 2,
        },
    )
    assert multi.status_code == 200, multi.text
    prop = multi.json()["proposal"]
    assert len(prop["seeds_uv"]) >= 2
    assert prop["expand_passes"] == 2

    stale = client.post(
        f"/api/studio/{clip_id}/grade/object-select",
        json={"u": 0.5, "v": 0.5, "expected_revision": rev + 99},
    )
    assert stale.status_code == 409


def test_mask_crud_rename_bind_overlay_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed_photo(db, tmp_path / "lib")
    grade = _ensure_managed(client, clip_id)
    rev = int(grade["revision"])

    leaf = {
        "id": "sel-leaf",
        "name": "Blatt",
        "invert": False,
        "overlay": {"visible": True},
        "mask": {
            "combine": "union",
            "leaves": [
                {
                    "type": "polygon",
                    "points": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]],
                    "feather": 0.02,
                    "closed": True,
                }
            ],
        },
        "qualifier": {"type": "none"},
    }
    put = client.post(
        f"/api/studio/{clip_id}/grade/command",
        json={
            "type": "upsert_selection",
            "expected_revision": rev,
            "params": {"selection": leaf},
        },
    )
    assert put.status_code == 200, put.text
    rev = int(put.json()["revision"])

    bind = client.post(
        f"/api/studio/{clip_id}/grade/command",
        json={
            "type": "upsert_step_params",
            "expected_revision": rev,
            "params": {
                "step_id": "primaries-1",
                "type": "primaries-v1",
                "selection_id": "sel-leaf",
                "params": {"saturation": 1.2},
                "enabled": True,
                "mix": 1.0,
            },
        },
    )
    assert bind.status_code == 200, bind.text
    rev = int(bind.json()["revision"])

    overlay = client.get(
        f"/api/studio/{clip_id}/grade/selection-overlay",
        params={"selection_id": "sel-leaf"},
    )
    assert overlay.status_code == 200
    assert overlay.headers.get("X-Orga-Overlay") == "preview-only"
    assert overlay.headers.get("content-type", "").startswith("image/")

    renamed = dict(leaf)
    renamed["name"] = "Leaf"
    renamed["overlay"] = {"visible": False}
    put = client.post(
        f"/api/studio/{clip_id}/grade/command",
        json={
            "type": "upsert_selection",
            "expected_revision": rev,
            "params": {"selection": renamed},
        },
    )
    assert put.status_code == 200
    rev = int(put.json()["revision"])
    grade = client.get(f"/api/studio/{clip_id}/grade").json()
    sel = next(s for s in grade["grade"]["selections"] if s["id"] == "sel-leaf")
    assert sel["name"] == "Leaf"
    assert sel["overlay"]["visible"] is False

    out = tmp_path / "export.jpg"
    started = client.post(
        f"/api/studio/{clip_id}/still/export",
        json={"format": "jpeg", "preset": "best", "output_path": str(out)},
    )
    assert started.status_code == 200, started.text
    job_id = started.json()["job_id"]
    st = None
    for _ in range(200):
        st = client.get(f"/api/studio/export/jobs/{job_id}").json()
        if st.get("state") in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.05)
    assert st is not None
    assert st.get("state") == "completed", st
    export_path = Path(st.get("output_path") or out)
    assert export_path.is_file()
    # Overlay must not bake cyan/preview tint into pixels: file is a real JPEG.
    with Image.open(export_path) as exported:
        assert exported.size[0] >= 16
        assert exported.format in {"JPEG", "MPO"}

    # Persistence after export: rename/delete still works on current revision.
    grade = client.get(f"/api/studio/{clip_id}/grade").json()
    rev = int(grade["revision"])
    delete = client.post(
        f"/api/studio/{clip_id}/grade/command",
        json={
            "type": "remove_selection",
            "expected_revision": rev,
            "params": {"selection_id": "sel-leaf"},
        },
    )
    assert delete.status_code == 200, delete.text
