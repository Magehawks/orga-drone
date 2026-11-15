"""Per-leaf collage grading reuses Color Workspace helpers (#469)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.i18n import clear_catalog_cache
from orga_drone.studio_collage import assign_leaf_media, collage_spec_from_raw, iter_leaves
from orga_drone.studio_collage_grade import apply_hsl, clear_leaf_grade, grade_blob
from orga_drone.studio_collage_still import render_collage_preview_png
from orga_drone.studio_hsl import hsl_adjust_from_effect_settings
from orga_drone.studio_image import image_adjust_from_effect_settings


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prefs = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr("orga_drone.app.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_collage_still.settings", prefs)
    clear_catalog_cache()
    from orga_drone.app import create_app

    return create_app()


def _seed_photos(db: Database, root: Path, count: int = 2) -> list[int]:
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label="t")
    ids: list[int] = []
    for i in range(count):
        name = f"leaf{i}.jpg"
        path = root / name
        Image.new("RGB", (120, 80), (30 + i * 80, 90, 140)).save(path, format="JPEG")
        mid = db.upsert_media(
            {
                "root_id": root_id,
                "primary_asset_id": None,
                "kind": "photo",
                "filename": name,
                "path": str(path.resolve()),
                "size_bytes": path.stat().st_size,
                "duration_s": None,
                "recorded_at": "2024-06-01T12:00:00",
                "sequence": None,
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
        ids.append(mid)
    return ids


def _seeded_collage(db: Database, root: Path):
    ids = _seed_photos(db, root, 2)
    project = db.create_studio_project("Leaf grade")
    collage = db.add_studio_collage(project.id, preset="1+1")
    spec = collage_spec_from_raw(collage.collage_spec)
    leaves = iter_leaves(spec["root"])
    leaf_ids = [str(leaf["id"]) for leaf in leaves]
    for leaf_id, mid in zip(leaf_ids, ids, strict=True):
        media = {
            "source": "library",
            "kind": "photo",
            "media_id": mid,
            "fit": "fill",
            "zoom": 1.0,
            "pan_x": 0.5,
            "pan_y": 0.5,
            "start_offset_s": 0.0,
        }
        spec = assign_leaf_media(spec, leaf_id, media)
    collage = db.update_studio_collage(collage.id, collage_spec=spec)
    return collage, leaf_ids, ids


def test_two_leaves_hold_independent_hsl(tmp_path: Path) -> None:
    db = Database(tmp_path / "lib.sqlite3")
    collage, leaf_ids, _ids = _seeded_collage(db, tmp_path / "media")
    spec = collage_spec_from_raw(collage.collage_spec)
    a = apply_hsl(
        spec,
        leaf_ids[0],
        {"ranges": {"red": {"hue": 40, "saturation": 0, "luminance": 0}}},
    )
    b = apply_hsl(
        a,
        leaf_ids[1],
        {"ranges": {"blue": {"hue": -30, "saturation": 20, "luminance": 0}}},
    )
    leaves = {str(leaf["id"]): leaf for leaf in iter_leaves(b["root"])}
    hsl_a = hsl_adjust_from_effect_settings(
        grade_blob(leaves[leaf_ids[0]].get("media"))
    )
    hsl_b = hsl_adjust_from_effect_settings(
        grade_blob(leaves[leaf_ids[1]].get("media"))
    )
    assert hsl_a.red.hue == 40
    assert hsl_a.blue.hue == 0
    assert hsl_b.blue.hue == -30
    assert hsl_b.red.hue == 0
    cleared = clear_leaf_grade(b, leaf_ids[0])
    leaves2 = {str(leaf["id"]): leaf for leaf in iter_leaves(cleared["root"])}
    assert "grade" not in (leaves2[leaf_ids[0]].get("media") or {})
    assert "grade" in (leaves2[leaf_ids[1]].get("media") or {})


def test_api_leaf_hsl_and_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    collage, leaf_ids, _ids = _seeded_collage(db, tmp_path / "lib")
    db.set_open_studio_project_id(collage.project_id)
    client = TestClient(app)
    client.get(f"/studio?project_id={collage.project_id}")

    res = client.patch(
        f"/api/studio/{collage.id}/hsl",
        json={
            "leaf_id": leaf_ids[0],
            "ranges": {"green": {"hue": 12, "saturation": -10, "luminance": 5}},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["leaf_id"] == leaf_ids[0]
    assert body["hsl"]["ranges"]["green"]["hue"] == 12

    other = client.patch(
        f"/api/studio/{collage.id}/hsl",
        json={
            "leaf_id": leaf_ids[1],
            "ranges": {"aqua": {"hue": -8, "saturation": 0, "luminance": 0}},
        },
    )
    assert other.status_code == 200
    assert other.json()["hsl"]["ranges"]["aqua"]["hue"] == -8

    refreshed = db.list_studio_items(collage.project_id)
    clip = next(i for i in refreshed if i.id == collage.id)
    leaves = {
        str(leaf["id"]): leaf
        for leaf in iter_leaves(collage_spec_from_raw(clip.collage_spec)["root"])
    }
    assert (leaves[leaf_ids[0]].get("media") or {}).get("grade")
    assert (leaves[leaf_ids[1]].get("media") or {}).get("grade")

    imaged = client.patch(
        f"/api/studio/{collage.id}/image",
        json={"leaf_id": leaf_ids[0], "exposure": 40},
    )
    assert imaged.status_code == 200
    assert imaged.json()["image"]["exposure"] == 40
    clip2 = next(i for i in db.list_studio_items(collage.project_id) if i.id == collage.id)
    leaves2 = {
        str(leaf["id"]): leaf
        for leaf in iter_leaves(collage_spec_from_raw(clip2.collage_spec)["root"])
    }
    image = image_adjust_from_effect_settings(
        grade_blob(leaves2[leaf_ids[0]].get("media"))
    )
    assert image.exposure == 40
    # Other leaf grade unchanged (still has aqua HSL, no exposure).
    other_image = image_adjust_from_effect_settings(
        grade_blob(leaves2[leaf_ids[1]].get("media"))
    )
    assert other_image.exposure == 0


def test_leaf_grade_affects_composed_still(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefs = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr("orga_drone.studio_collage_still.settings", prefs)
    db = Database(tmp_path / "lib.sqlite3")
    collage, leaf_ids, _ids = _seeded_collage(db, tmp_path / "media")
    neutral_spec = collage_spec_from_raw(collage.collage_spec)
    neutral = render_collage_preview_png(db, neutral_spec, t_s=0.0, long_edge=320)
    assert neutral
    with Image.open(__import__("io").BytesIO(neutral)) as img:
        neutral_px = img.getpixel((20, 20))

    graded = db.set_studio_collage_leaf_grade(
        collage.id,
        leaf_ids[0],
        section="image",
        payload={"exposure": 80},
    )
    graded_spec = collage_spec_from_raw(graded.collage_spec)
    out = render_collage_preview_png(db, graded_spec, t_s=0.0, long_edge=320)
    assert out
    with Image.open(__import__("io").BytesIO(out)) as img:
        graded_px = img.getpixel((20, 20))
    assert graded_px != neutral_px
