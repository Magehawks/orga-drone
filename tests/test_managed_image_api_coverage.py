"""Managed image API coverage for adjustments + selections (#512 / #506)."""

from __future__ import annotations

import hashlib
import io
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.studio_grade_persistence import startup_backup_if_needed


def _mean_chroma(path_or_bytes: Path | bytes) -> float:
    if isinstance(path_or_bytes, bytes):
        img = Image.open(io.BytesIO(path_or_bytes))
    else:
        img = Image.open(path_or_bytes)
    with img:
        pixels = list(img.convert("RGB").getdata())
    total = 0.0
    for r, g, b in pixels:
        mx = max(r, g, b)
        mn = min(r, g, b)
        total += (mx - mn) / 255.0
    return total / max(1, len(pixels))


def _channel_means(path_or_bytes: Path | bytes) -> tuple[float, float, float]:
    if isinstance(path_or_bytes, bytes):
        img = Image.open(io.BytesIO(path_or_bytes))
    else:
        img = Image.open(path_or_bytes)
    with img:
        pixels = list(img.convert("RGB").getdata())
    n = max(1, len(pixels))
    return (
        sum(p[0] for p in pixels) / n,
        sum(p[1] for p in pixels) / n,
        sum(p[2] for p in pixels) / n,
    )


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database, Path]:
    data_dir = tmp_path / "data"
    settings = Settings(data_dir=data_dir)
    monkeypatch.setattr("orga_drone.app.settings", settings)
    monkeypatch.setattr("orga_drone.config.settings", settings)
    monkeypatch.setattr("orga_drone.app_prefs.settings", settings)
    monkeypatch.setattr("orga_drone.studio_export.settings", settings)
    monkeypatch.setattr("orga_drone.studio_clip_still.settings", settings)
    monkeypatch.setattr("orga_drone.studio_preview_frame.settings", settings, raising=False)
    startup_backup_if_needed(data_dir, app_version="test")
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db, tmp_path / "lib"


def _seed_photo(
    db: Database, lib: Path, *, size=(96, 72), color=(200, 80, 50)
) -> tuple[int, Path, str]:
    lib.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(lib, label="t")
    photo = lib / "leaf.jpg"
    Image.new("RGB", size, color).save(photo, quality=92)
    source_sha = hashlib.sha256(photo.read_bytes()).hexdigest()
    media_id = db.upsert_media(
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
    item = db.get_media(media_id)
    assert item is not None
    clip_id, _ = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
    )
    return clip_id, photo, source_sha


def _ensure_managed(client: TestClient, clip_id: int) -> tuple[dict, int]:
    current = client.get(f"/api/studio/{clip_id}/grade").json()
    if current.get("evaluator") != "managed-sdr-v1":
        assert client.post(f"/api/studio/{clip_id}/grade/wrap").status_code == 200
        conv = client.post(
            f"/api/studio/{clip_id}/grade/convert-managed",
            json={"acknowledge_appearance_change": True},
        )
        assert conv.status_code == 200, conv.text
        current = client.get(f"/api/studio/{clip_id}/grade").json()
    return current["grade"], int(current["revision"])


def _put(client: TestClient, clip_id: int, grade: dict, rev: int) -> int:
    put = client.put(
        f"/api/studio/{clip_id}/grade",
        json={"grade": grade, "expected_revision": rev},
    )
    assert put.status_code == 200, put.text
    return int(put.json()["revision"])


def _wait_job(client: TestClient, job_id: str, *, timeout_s: float = 45.0) -> dict:
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    while time.monotonic() < deadline:
        last = client.get(f"/api/studio/export/jobs/{job_id}").json()
        if last.get("state") in {"completed", "failed", "cancelled"}:
            return last
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} timed out: {last}")


def test_invalid_revision_and_unknown_op_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db, lib = _client(tmp_path, monkeypatch)
    clip_id, _, _ = _seed_photo(db, lib)
    grade, rev = _ensure_managed(client, clip_id)
    stale = client.put(
        f"/api/studio/{clip_id}/grade",
        json={"grade": grade, "expected_revision": rev + 99},
    )
    assert stale.status_code == 409
    bad = client.post(
        f"/api/studio/{clip_id}/grade/command",
        json={
            "type": "not-a-real-command",
            "expected_revision": rev,
            "params": {},
        },
    )
    assert bad.status_code in {400, 422}


def test_primaries_hsl_selection_preview_export_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORGA_SPATIAL_BAKE_INLINE", "1")
    client, db, lib = _client(tmp_path, monkeypatch)
    clip_id, source, source_sha = _seed_photo(
        db, lib, size=(96, 72), color=(200, 80, 50)
    )
    grade, rev = _ensure_managed(client, clip_id)
    source_chroma = _mean_chroma(source)

    # Large radial covers most of the frame so grade is measurable on solid fill.
    grade["selections"] = [
        {
            "id": "sel-leaf",
            "invert": False,
            "mask": {
                "combine": "union",
                "leaves": [
                    {
                        "type": "radial",
                        "center": [0.5, 0.5],
                        "axes": [0.55, 0.55],
                        "feather": 0.05,
                    }
                ],
            },
            "qualifier": {"type": "none"},
        },
        {
            "id": "sel-bg",
            "invert": True,
            "mask": {
                "combine": "union",
                "leaves": [
                    {
                        "type": "radial",
                        "center": [0.5, 0.5],
                        "axes": [0.55, 0.55],
                        "feather": 0.05,
                    }
                ],
            },
            "qualifier": {"type": "none"},
        },
    ]
    grade["steps"] = [
        {
            "id": "primaries-leaf",
            "type": "primaries-v1",
            "enabled": True,
            "mix": 1.0,
            "selection_id": "sel-leaf",
            "params": {
                "exposure": 0.05,
                "kelvin": 4200,
                "tint": 80,
                "contrast": 1.1,
                "pivot": 0.4,
                "saturation": 1.4,
                "blacks": -5,
                "shadows": 10,
                "highlights": -20,
                "whites": -10,
            },
        },
        {
            "id": "hsl-bg",
            "type": "managed-hsl-v1",
            "enabled": True,
            "mix": 1.0,
            "selection_id": "sel-bg",
            "params": {"hue": 0, "saturation": 0.0, "lightness": -0.05},
        },
    ]
    rev = _put(client, clip_id, grade, rev)

    reopen = client.get(f"/api/studio/{clip_id}/grade").json()
    assert reopen["revision"] == rev
    assert reopen["grade"]["steps"][0]["params"]["tint"] == 80
    assert reopen["grade"]["selections"][1]["invert"] is True

    preview = client.get(
        f"/api/studio/{clip_id}/preview-frame",
        params={"t_s": 0, "expected_revision": rev},
    )
    assert preview.status_code == 200, preview.text
    assert preview.headers.get("content-type", "").startswith("image/")
    preview_chroma = _mean_chroma(preview.content)
    preview_means = _channel_means(preview.content)
    # Spatial grade must change appearance vs source (tint/sat path).
    assert abs(preview_chroma - source_chroma) > 0.02 or abs(
        preview_means[0] - 200
    ) > 5

    out = tmp_path / "out.jpg"
    job = client.post(
        f"/api/studio/{clip_id}/still/export",
        json={"format": "jpeg", "preset": "best", "output_path": str(out)},
    )
    assert job.status_code == 200, job.text
    st = _wait_job(client, job.json()["job_id"])
    assert st["state"] == "completed", st
    assert out.is_file() and out.stat().st_size > 0
    export_chroma = _mean_chroma(out)
    export_means = _channel_means(out)
    # Preview and export should land in the same ballpark (spatial CPU path).
    assert abs(export_chroma - preview_chroma) < 0.15
    assert abs(export_means[0] - preview_means[0]) < 25
    assert abs(export_means[1] - preview_means[1]) < 25
    assert abs(export_means[2] - preview_means[2]) < 25
    # Source media untouched.
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha

    cmd = client.post(
        f"/api/studio/{clip_id}/grade/command",
        json={
            "type": "upsert_step_params",
            "expected_revision": rev,
            "params": {
                "step_id": "primaries-leaf",
                "type": "primaries-v1",
                "params": {"exposure": 0.2},
            },
        },
    )
    assert cmd.status_code == 200, cmd.text
    assert int(cmd.json()["revision"]) > rev
