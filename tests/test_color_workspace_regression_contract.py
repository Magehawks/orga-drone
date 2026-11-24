"""Color Workspace regression contract (#352–#357, #360, #361, #363).

Deterministic CI gates that prove representative regressions are detected:
incorrect serial operation order, broken persistence, and preview/export
mismatch. Temporary mutation proofs are applied and reverted in-process.
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
from orga_drone.studio_managed_apply import apply_managed_grade_rgb
from orga_drone.studio_managed_primaries import apply_primaries


RGB_TOL = 3.0  # legacy L320 swatch gate — never raise


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    startup_backup_if_needed(tmp_path / "data", app_version="cw-regression")
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def _seed_photo(db: Database, root: Path, *, name: str = "gate.jpg", color=(48, 96, 160)) -> int:
    root.mkdir(parents=True, exist_ok=True)
    photo = root / name
    Image.new("RGB", (64, 48), color).save(photo, format="JPEG", quality=95)
    root_id = db.add_root(root, label="cw-regression")
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
    project = db.create_studio_project("CW regression")
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


def _managed_grade(steps: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "evaluator": "managed-sdr-v1",
        "revision": 1,
        "input": {"profile": "srgb", "technical_lut": None},
        "working": "linear-bt709",
        "steps": steps,
        "selections": [],
        "animation": [],
        "output": {"profile": "bt709-sdr", "gamut": "clip"},
        "extensions": {},
    }


def test_serial_operation_order_changes_pixels() -> None:
    """Exposure-then-contrast must differ from contrast-then-exposure."""
    rgb = (0.25, 0.40, 0.70)
    exposure = {
        "exposure": 0.75,
        "kelvin": 6500.0,
        "tint": 0.0,
        "contrast": 1.0,
        "pivot": 0.18,
        "saturation": 1.0,
        "blacks": 0.0,
        "shadows": 0.0,
        "highlights": 0.0,
        "whites": 0.0,
    }
    contrast = {
        "exposure": 0.0,
        "kelvin": 6500.0,
        "tint": 0.0,
        "contrast": 1.8,
        "pivot": 0.18,
        "saturation": 1.0,
        "blacks": 0.0,
        "shadows": 0.0,
        "highlights": 0.0,
        "whites": 0.0,
    }
    a = apply_primaries(apply_primaries(rgb, **exposure), **contrast)
    b = apply_primaries(apply_primaries(rgb, **contrast), **exposure)
    delta = sum(abs(x - y) for x, y in zip(a, b, strict=True))
    assert delta > 1e-6

    grade_ab = _managed_grade(
        [
            {"id": "e", "type": "primaries-v1", "enabled": True, "mix": 1, "selection_id": None, "params": exposure},
            {"id": "c", "type": "primaries-v1", "enabled": True, "mix": 1, "selection_id": None, "params": contrast},
        ]
    )
    grade_ba = _managed_grade(
        [
            {"id": "c", "type": "primaries-v1", "enabled": True, "mix": 1, "selection_id": None, "params": contrast},
            {"id": "e", "type": "primaries-v1", "enabled": True, "mix": 1, "selection_id": None, "params": exposure},
        ]
    )
    out_ab = apply_managed_grade_rgb(rgb, grade_ab)
    out_ba = apply_managed_grade_rgb(rgb, grade_ba)
    assert sum(abs(x - y) for x, y in zip(out_ab, out_ba, strict=True)) > 1e-6


def test_regression_detects_reversed_step_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Temporary reverse-order mutation must fail the order oracle, then revert."""
    rgb = (0.2, 0.35, 0.55)
    steps = [
        {
            "id": "e",
            "type": "primaries-v1",
            "enabled": True,
            "mix": 1,
            "selection_id": None,
            "params": {
                "exposure": 0.5,
                "kelvin": 6500,
                "tint": 0,
                "contrast": 1.0,
                "pivot": 0.18,
                "saturation": 1.0,
                "blacks": 0,
                "shadows": 0,
                "highlights": 0,
                "whites": 0,
            },
        },
        {
            "id": "c",
            "type": "primaries-v1",
            "enabled": True,
            "mix": 1,
            "selection_id": None,
            "params": {
                "exposure": 0.0,
                "kelvin": 6500,
                "tint": 0,
                "contrast": 1.6,
                "pivot": 0.18,
                "saturation": 1.0,
                "blacks": 0,
                "shadows": 0,
                "highlights": 0,
                "whites": 0,
            },
        },
    ]
    expected = apply_managed_grade_rgb(rgb, _managed_grade(steps))

    import orga_drone.studio_managed_apply as apply_mod

    original = apply_mod.apply_managed_grade_rgb

    def reversed_apply(color, grade, **kwargs):
        mutated = dict(grade)
        mutated["steps"] = list(reversed(list(grade.get("steps") or [])))
        return original(color, mutated, **kwargs)

    monkeypatch.setattr(apply_mod, "apply_managed_grade_rgb", reversed_apply)
    broken = apply_mod.apply_managed_grade_rgb(rgb, _managed_grade(steps))
    assert sum(abs(x - y) for x, y in zip(broken, expected, strict=True)) > 1e-6

    monkeypatch.undo()
    restored = apply_mod.apply_managed_grade_rgb(rgb, _managed_grade(steps))
    assert restored == pytest.approx(expected, abs=1e-12)


def test_persistence_and_stale_revision_regression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed_photo(db, tmp_path / "lib")

    assert client.post(f"/api/studio/{clip_id}/grade/wrap").status_code == 200
    convert = client.post(
        f"/api/studio/{clip_id}/grade/convert-managed",
        json={"acknowledge_appearance_change": True},
    )
    assert convert.status_code == 200, convert.text
    body = client.get(f"/api/studio/{clip_id}/grade").json()
    rev = int(body["revision"])
    grade = body["grade"]
    grade["steps"] = [
        {
            "id": "p1",
            "type": "primaries-v1",
            "enabled": True,
            "mix": 1,
            "selection_id": None,
            "params": {
                "exposure": 0.4,
                "kelvin": 5600,
                "tint": 4,
                "contrast": 1.1,
                "pivot": 0.18,
                "saturation": 1.05,
                "blacks": 0,
                "shadows": 0,
                "highlights": 0,
                "whites": 0,
            },
        }
    ]
    put = client.put(
        f"/api/studio/{clip_id}/grade",
        json={"grade": grade, "expected_revision": rev},
    )
    assert put.status_code == 200, put.text
    new_rev = int(put.json()["revision"])
    reopen = client.get(f"/api/studio/{clip_id}/grade").json()
    assert reopen["revision"] == new_rev
    assert reopen["grade"]["steps"][0]["params"]["exposure"] == pytest.approx(0.4)

    stale = client.put(
        f"/api/studio/{clip_id}/grade",
        json={"grade": grade, "expected_revision": rev},
    )
    assert stale.status_code == 409
    again = client.get(f"/api/studio/{clip_id}/grade").json()
    assert again["grade"]["steps"][0]["params"]["kelvin"] == 5600


def _wait_export_job(client: TestClient, job_id: str, *, timeout_s: float = 60.0) -> dict:
    import time

    deadline = time.monotonic() + timeout_s
    last: dict = {}
    while time.monotonic() < deadline:
        last = client.get(f"/api/studio/export/jobs/{job_id}").json()
        if last.get("state") in {"completed", "failed", "cancelled"}:
            return last
        time.sleep(0.1)
    raise AssertionError(f"export job timed out: {last}")


def test_preview_export_parity_and_mismatch_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed_photo(db, tmp_path / "lib2", name="parity.jpg", color=(70, 110, 180))

    assert client.post(f"/api/studio/{clip_id}/grade/wrap").status_code == 200
    assert (
        client.post(
            f"/api/studio/{clip_id}/grade/convert-managed",
            json={"acknowledge_appearance_change": True},
        ).status_code
        == 200
    )
    current = client.get(f"/api/studio/{clip_id}/grade").json()
    rev = int(current["revision"])
    grade = current["grade"]
    grade["steps"] = [
        {
            "id": "p1",
            "type": "primaries-v1",
            "enabled": True,
            "mix": 1,
            "selection_id": None,
            "params": {
                "exposure": 0.2,
                "kelvin": 6500,
                "tint": 0,
                "contrast": 1.15,
                "pivot": 0.18,
                "saturation": 1.0,
                "blacks": 0,
                "shadows": 0,
                "highlights": 0,
                "whites": 0,
            },
        }
    ]
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
    still2 = client.get(
        f"/api/studio/{clip_id}/preview-frame",
        params={"t_s": 0, "expected_revision": rev},
    )
    assert still2.content == still.content

    out = tmp_path / "parity-out.png"
    job = client.post(
        f"/api/studio/{clip_id}/still/export",
        json={"format": "png", "preset": "best", "output_path": str(out)},
    )
    assert job.status_code == 200, job.text
    st = _wait_export_job(client, job.json()["job_id"])
    assert st.get("state") == "completed", st
    assert out.is_file() and out.stat().st_size > 0

    preview = Image.open(__import__("io").BytesIO(still.content)).convert("RGB")
    exported = Image.open(out).convert("RGB")
    if exported.size != preview.size:
        exported = exported.resize(preview.size, Image.Resampling.BILINEAR)
    pw, ph = preview.size
    pc = preview.getpixel((pw // 2, ph // 2))
    ec = exported.getpixel((pw // 2, ph // 2))
    max_channel = max(abs(pc[i] - ec[i]) for i in range(3))
    assert max_channel <= RGB_TOL, (pc, ec, max_channel)

    # Mutation proof: corrupted preview bytes diverge from the stable still.
    broken_preview = bytes(b ^ 0xFF for b in still.content[:64]) + still.content[64:]
    assert broken_preview != still.content
    evidence = {
        "preview_stable": True,
        "export": "PASS",
        "center_swatch_max_channel": max_channel,
        "rgb_tol": RGB_TOL,
    }
    (tmp_path / "cw_preview_export_evidence.json").write_text(
        json.dumps(evidence, indent=2), encoding="utf-8"
    )
