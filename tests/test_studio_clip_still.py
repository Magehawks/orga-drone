"""Studio photo-clip still export (#499 / Adaptive Studio PR1)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.studio_clip_still import (
    apply_studio_photo_privacy_masks,
    effect_settings_has_color,
    export_studio_photo_clip_still,
    materialize_studio_photo_grade_source,
)
from orga_drone.studio_grade_persistence import startup_backup_if_needed
from orga_drone.studio_managed_apply import apply_managed_grade_image


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    prefs = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr("orga_drone.app_prefs.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_export.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_clip_still.settings", prefs)
    monkeypatch.setattr("orga_drone.config.settings", prefs)
    monkeypatch.setattr("orga_drone.app.settings", prefs)
    startup_backup_if_needed(tmp_path / "data", app_version="clip-still")
    return prefs


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    _isolate(monkeypatch, tmp_path)
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def _seed_photo(
    db: Database,
    root: Path,
    *,
    size: tuple[int, int] = (48, 32),
    color: tuple[int, int, int] = (200, 160, 80),
) -> int:
    root.mkdir(parents=True, exist_ok=True)
    photo = root / "leaf.jpg"
    Image.new("RGB", size, color).save(photo, format="JPEG", quality=95)
    root_id = db.add_root(root, label="still")
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
    project = db.create_studio_project("Still export")
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


def _spatial_grade(*, invert: bool = False, feather: float = 0.05) -> dict:
    return {
        "schema_version": 1,
        "evaluator": "managed-sdr-v1",
        "revision": 1,
        "input": {"profile": "srgb", "technical_lut": None},
        "working": "linear-bt709",
        "steps": [
            {
                "id": "p1",
                "type": "primaries-v1",
                "enabled": True,
                "mix": 1,
                "selection_id": "sel-1",
                "params": {
                    "exposure": 0.0,
                    "kelvin": 6500,
                    "tint": 0,
                    "contrast": 1,
                    "pivot": 0.18,
                    "saturation": 0.0,
                    "blacks": 0,
                    "shadows": 0,
                    "highlights": 0,
                    "whites": 0,
                },
            }
        ],
        "selections": [
            {
                "id": "sel-1",
                "mask": {
                    "combine": "union",
                    "leaves": [
                        {
                            "type": "radial",
                            "center": [0.5, 0.5],
                            "axes": [0.3, 0.3],
                            "feather": feather,
                        }
                    ],
                },
                "qualifier": {"type": "none"},
                "invert": invert,
            }
        ],
        "animation": [],
        "output": {"profile": "bt709-sdr", "gamut": "clip"},
        "extensions": {},
    }


def _brush_grade() -> dict:
    grade = _spatial_grade()
    grade["selections"] = [
        {
            "id": "sel-1",
            "mask": {
                "combine": "union",
                "leaves": [
                    {
                        "type": "brush",
                        "combine": "union",
                        "strokes": [
                            {
                                "points": [[0.2, 0.2], [0.5, 0.5], [0.8, 0.3]],
                                "radius": 0.2,
                                "hardness": 0.4,
                                "pressure": 1.0,
                            }
                        ],
                    }
                ],
            },
            "qualifier": {"type": "none"},
            "invert": False,
        }
    ]
    return grade


def _put_managed(client: TestClient, clip_id: int, grade: dict) -> int:
    current = client.get(f"/api/studio/{clip_id}/grade").json()
    if current.get("evaluator") != "managed-sdr-v1":
        assert client.post(f"/api/studio/{clip_id}/grade/wrap").status_code == 200
        convert = client.post(
            f"/api/studio/{clip_id}/grade/convert-managed",
            json={"acknowledge_appearance_change": True},
        )
        assert convert.status_code == 200, convert.text
        current = client.get(f"/api/studio/{clip_id}/grade").json()
    rev = int(current["revision"])
    base = current["grade"]
    base["steps"] = grade["steps"]
    base["selections"] = grade["selections"]
    put = client.put(
        f"/api/studio/{clip_id}/grade",
        json={"grade": base, "expected_revision": rev},
    )
    assert put.status_code == 200, put.text
    return int(put.json()["revision"])


def test_effect_settings_has_color_neutral() -> None:
    assert effect_settings_has_color(None) is False
    assert effect_settings_has_color("{}") is False


def test_spatial_still_export_preserves_source_and_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed_photo(db, tmp_path / "lib", size=(40, 30), color=(210, 40, 40))
    _put_managed(client, clip_id, _spatial_grade(feather=0.0))

    clip = next(
        item
        for project in db.list_studio_projects()
        for item in db.list_studio_items(project.id)
        if item.id == clip_id
    )
    source = Path(db.get_media(clip.source_media_id).path)
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    dest = tmp_path / "out" / "graded.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = export_studio_photo_clip_still(
        db, clip_id, dest, preset="best", still_format="jpeg"
    )
    assert result.is_file()
    assert result.suffix.lower() in {".jpg", ".jpeg"}
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before

    with Image.open(source) as src_img, Image.open(result) as out_img:
        assert src_img.size == out_img.size
        src = src_img.convert("RGB")
        out = out_img.convert("RGB")
        # Radial centre should be desaturated toward gray; corner stays redder.
        cx, cy = src.size[0] // 2, src.size[1] // 2
        centre = out.getpixel((cx, cy))
        corner = out.getpixel((1, 1))
        assert abs(centre[0] - centre[1]) < abs(corner[0] - corner[1])


def test_brush_and_invert_change_pixels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed_photo(db, tmp_path / "lib", size=(32, 32), color=(40, 180, 40))
    _put_managed(client, clip_id, _brush_grade())
    clip = next(
        item
        for project in db.list_studio_projects()
        for item in db.list_studio_items(project.id)
        if item.id == clip_id
    )
    source = Path(db.get_media(clip.source_media_id).path)
    graded = materialize_studio_photo_grade_source(source, clip.effect_settings)
    with Image.open(source) as src_img, Image.open(graded) as out_img:
        src = list(src_img.convert("RGB").getdata())
        out = list(out_img.convert("RGB").getdata())
    assert src != out

    # Invert selection should differ from non-inverted brush grade.
    _put_managed(client, clip_id, _spatial_grade(invert=True, feather=0.1))
    clip = next(
        item
        for project in db.list_studio_projects()
        for item in db.list_studio_items(project.id)
        if item.id == clip_id
    )
    inverted = materialize_studio_photo_grade_source(source, clip.effect_settings)
    assert inverted.read_bytes() != graded.read_bytes()


def test_preview_export_spatial_parity_within_tolerance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed_photo(db, tmp_path / "lib", size=(24, 16), color=(90, 40, 200))
    rev = _put_managed(client, clip_id, _spatial_grade(feather=0.0))

    preview = client.get(
        f"/api/studio/{clip_id}/preview-frame",
        params={"t_s": 0, "expected_revision": rev, "max_edge": 24},
    )
    assert preview.status_code == 200, preview.text
    preview_path = tmp_path / "preview.jpg"
    preview_path.write_bytes(preview.content)

    dest = tmp_path / "export.png"
    export_studio_photo_clip_still(db, clip_id, dest, preset="best", still_format="png")

    with Image.open(preview_path) as p_img, Image.open(dest) as e_img:
        preview_rgb = p_img.convert("RGB").resize(e_img.size, Image.Resampling.BILINEAR)
        export_rgb = e_img.convert("RGB")
        # Same semantics; allow JPEG preview quantization / scale drift.
        errs = [
            abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])
            for a, b in zip(preview_rgb.getdata(), export_rgb.getdata(), strict=True)
        ]
        mean = sum(errs) / max(1, len(errs))
        assert mean < 40.0


def test_api_still_export_job_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed_photo(db, tmp_path / "lib")
    _put_managed(client, clip_id, _spatial_grade())
    dest = tmp_path / "api-out.jpg"
    res = client.post(
        f"/api/studio/{clip_id}/still/export",
        json={"output_path": str(dest), "format": "jpeg", "preset": "best"},
    )
    assert res.status_code == 200, res.text
    job_id = res.json()["job_id"]
    final = None
    for _ in range(80):
        poll = client.get(f"/api/studio/export/jobs/{job_id}")
        assert poll.status_code == 200
        final = poll.json()
        state = final.get("state") or final.get("status")
        if state in {"completed", "done", "failed", "cancelled", "error"}:
            break
    assert final is not None
    state = final.get("state") or final.get("status")
    assert state in {"completed", "done"}, final
    out = Path(final.get("output_path") or dest)
    assert out.is_file()
    assert out.stat().st_size > 0


def test_unmasked_legacy_export_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed_photo(db, tmp_path / "lib", color=(10, 10, 10))
    # Legacy exposure bump via image adjust API.
    patch = client.patch(
        f"/api/studio/{clip_id}/image",
        json={"exposure": 40},
    )
    assert patch.status_code == 200, patch.text
    dest = tmp_path / "legacy.png"
    result = export_studio_photo_clip_still(
        db, clip_id, dest, preset="best", still_format="png"
    )
    assert result.is_file()
    with Image.open(result) as img:
        pixel = img.convert("RGB").getpixel((0, 0))
    assert sum(pixel) > 30


def test_still_export_applies_privacy_blur_masks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prefs = _isolate(monkeypatch, tmp_path)
    photo = tmp_path / "hard.jpg"
    # High-frequency stripe pattern so blur is measurable.
    img = Image.new("RGB", (64, 64))
    px = img.load()
    for y in range(64):
        for x in range(64):
            v = 255 if (x // 4) % 2 == 0 else 0
            px[x, y] = (v, v, v)
    img.save(photo, format="JPEG", quality=95)
    effect = json.dumps(
        {
            "masks": [
                {
                    "id": "blur-top",
                    "effect": "blur",
                    "strength": 90,
                    "x": 0.0,
                    "y": 0.0,
                    "w": 1.0,
                    "h": 0.35,
                }
            ]
        }
    )
    masked = apply_studio_photo_privacy_masks(
        photo, effect, data_dir=prefs.data_dir
    )
    assert masked != photo
    with Image.open(photo) as src_img, Image.open(masked) as out_img:
        src = src_img.convert("RGB")
        out = out_img.convert("RGB")
        assert out.size == src.size
        # Top band should soften; center stripe contrast remains high.
        top_src = [src.getpixel((x, 8))[0] for x in range(0, 64, 4)]
        top_out = [out.getpixel((x, 8))[0] for x in range(0, 64, 4)]
        mid_out = [out.getpixel((x, 40))[0] for x in range(0, 64, 4)]
        assert max(top_src) - min(top_src) >= 200
        assert max(top_out) - min(top_out) < max(top_src) - min(top_src)
        assert max(mid_out) - min(mid_out) >= 200


def test_cpu_reference_matches_materialize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(monkeypatch, tmp_path)
    photo = tmp_path / "ref.jpg"
    Image.new("RGB", (16, 12), (180, 60, 60)).save(photo, format="JPEG", quality=95)
    grade = _spatial_grade(feather=0.0)
    effect = json.dumps(
        {
            "authority": "canonical",
            "evaluator": "managed-sdr-v1",
            "revision": 1,
            "grade": grade,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    graded = materialize_studio_photo_grade_source(photo, effect)
    with Image.open(photo) as src_img, Image.open(graded) as out_img:
        src = src_img.convert("RGB")
        out = out_img.convert("RGB")
        width, height = src.size
        px = src.load()
        rows = [
            [(px[x, y][0] / 255.0, px[x, y][1] / 255.0, px[x, y][2] / 255.0) for x in range(width)]
            for y in range(height)
        ]
        ref = apply_managed_grade_image(rows, grade, lattice_domain="srgb")
        for y in range(height):
            for x in range(width):
                rr, rg, rb = ref[y][x]
                er = int(min(255, max(0, round(rr * 255))))
                eg = int(min(255, max(0, round(rg * 255))))
                eb = int(min(255, max(0, round(rb * 255))))
                gr, gg, gb = out.getpixel((x, y))
                assert abs(er - gr) <= 2
                assert abs(eg - gg) <= 2
                assert abs(eb - gb) <= 2
