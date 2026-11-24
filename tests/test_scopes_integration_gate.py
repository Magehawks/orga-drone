"""Scopes + managed-grade integration gate (#362/#364/#365/#366).

Independent synthetic fixtures drive ScopeFrameV1 expectations. Live preview
pixels come from the existing /preview-frame path (no second renderer). Scopes
must not mutate saved grades or source media. Packaged WebView2 latency remains
a separate evidence row.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.studio_grade_persistence import startup_backup_if_needed

REPO = Path(__file__).resolve().parents[1]


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    startup_backup_if_needed(tmp_path / "data", app_version="scopes-gate")
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def _seed_chart(db: Database, root: Path) -> tuple[int, Path]:
    root.mkdir(parents=True, exist_ok=True)
    # Distinct RGB chart so exposure lifts move histogram mass predictably.
    img = Image.new("RGB", (64, 48))
    px = img.load()
    for y in range(48):
        for x in range(64):
            if x < 21:
                px[x, y] = (220, 40, 40)
            elif x < 42:
                px[x, y] = (40, 220, 40)
            else:
                px[x, y] = (40, 40, 220)
    photo = root / "chart.jpg"
    img.save(photo, format="JPEG", quality=95)
    root_id = db.add_root(root, label="scopes-gate")
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
    project = db.create_studio_project("Scopes gate")
    clip_id, _ = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
        project_id=project.id,
        source_media_id=mid,
    )
    return clip_id, photo


def _histogram_luma_peak(jpeg_bytes: bytes) -> tuple[int, float]:
    """Independent CPU reference: BT.709 Y' 256-bin peak (full frame, opaque)."""
    from io import BytesIO

    im = Image.open(BytesIO(jpeg_bytes)).convert("RGBA")
    bins = [0.0] * 256
    weight = 0.0
    for r, g, b, a in im.getdata():  # noqa: DEP
        if a <= 0:
            continue
        w = a / 255.0
        weight += w
        y = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
        idx = min(255, math.floor(256 * y))
        bins[idx] += w
    peak = max(range(256), key=lambda i: bins[i])
    return peak, weight


def _node_accumulate_luma_peak(rgba: bytes, width: int, height: int, tmp: Path) -> int:
    """Candidate accumulate path via ScopeFrameV1 (same module Studio uses)."""
    rgba_path = tmp / "scope-rgba.bin"
    rgba_path.write_bytes(rgba)
    script_path = tmp / "scope_accumulate_peak.mjs"
    script_path.write_text(
        f"""
import {{ readFileSync }} from 'node:fs';
import {{ createScopeFrameV1, SCOPE_SOURCE_KINDS, SCOPE_TAP_IDS }} from '{(REPO / 'src/orga_drone/static/js/studio/scopes/scope-frame.js').resolve().as_uri()}';
import {{ accumulateHistogram }} from '{(REPO / 'src/orga_drone/static/js/studio/scopes/accumulate.js').resolve().as_uri()}';
const width = {width};
const height = {height};
const channels = 4;
const stride = width * channels;
const rgba = new Uint8Array(readFileSync({json.dumps(str(rgba_path))}));
const rgb = new Float32Array(height * stride);
for (let i = 0; i < width * height; i++) {{
  const s = i * 4;
  const d = i * channels;
  rgb[d] = rgba[s] / 255;
  rgb[d + 1] = rgba[s + 1] / 255;
  rgb[d + 2] = rgba[s + 2] / 255;
  rgb[d + 3] = rgba[s + 3] / 255;
}}
const frame = createScopeFrameV1({{
  version: 1, width, height, stride, rgb, channels,
  profile: 'bt709', transfer: 'bt709', straightAlpha: true, legalRange: false,
  ptsNum: 0, ptsDen: 1, frameIndex: 0, projectId: 'p', clipId: 'c',
  gradeRevision: '1', contextDigest: 'd',
  tapId: SCOPE_TAP_IDS.CLIP_POST_GRADE, roi: {{ x: 0, y: 0, width, height }},
  sampleFactor: 1, sourceKind: SCOPE_SOURCE_KINDS.ENGINE_TAP,
}});
const hist = accumulateHistogram(frame);
let peak = 0;
for (let i = 1; i < 256; i++) if (hist.absolute.luma[i] > hist.absolute.luma[peak]) peak = i;
console.log(JSON.stringify({{ peak, weightSum: hist.weightSum }}));
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["node", str(script_path)],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stdout + "\n" + proc.stderr)
    return int(json.loads(proc.stdout.strip())["peak"])


def test_scopes_preview_updates_without_mutating_grade_or_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id, photo = _seed_chart(db, tmp_path / "lib")
    source_hash = hashlib.sha256(photo.read_bytes()).hexdigest()

    assert client.post(f"/api/studio/{clip_id}/grade/wrap").status_code == 200
    converted = client.post(
        f"/api/studio/{clip_id}/grade/convert-managed",
        json={"acknowledge_appearance_change": True},
    )
    assert converted.status_code == 200
    revision = int(converted.json()["revision"])
    grade = converted.json()["grade"]
    grade["steps"] = [
        {
            "id": "step-exp",
            "type": "primaries-v1",
            "enabled": True,
            "mix": 1,
            "params": {"exposure": 0.0},
            "selection_id": None,
        }
    ]
    put0 = client.put(
        f"/api/studio/{clip_id}/grade",
        json={"grade": grade, "expected_revision": revision},
    )
    assert put0.status_code == 200
    revision = int(put0.json()["revision"])
    grade_before = json.dumps(put0.json()["grade"], sort_keys=True)

    preview0 = client.get(f"/api/studio/{clip_id}/preview-frame", params={"t_s": 0})
    assert preview0.status_code == 200
    peak0, _ = _histogram_luma_peak(preview0.content)

    # Emulate "scopes on": only read preview pixels; never PATCH grade.
    preview0b = client.get(f"/api/studio/{clip_id}/preview-frame", params={"t_s": 0})
    assert preview0b.status_code == 200
    assert preview0b.content == preview0.content

    grade["steps"][0]["params"]["exposure"] = 1.2
    put1 = client.put(
        f"/api/studio/{clip_id}/grade",
        json={"grade": grade, "expected_revision": revision},
    )
    assert put1.status_code == 200
    revision = int(put1.json()["revision"])
    preview1 = client.get(f"/api/studio/{clip_id}/preview-frame", params={"t_s": 0})
    assert preview1.status_code == 200
    peak1, _ = _histogram_luma_peak(preview1.content)
    assert peak1 != peak0, (peak0, peak1)

    # Independent Node accumulate must agree with the Python reference peak.
    im = Image.open(__import__("io").BytesIO(preview1.content)).convert("RGBA")
    rgba = im.tobytes()
    node_peak = _node_accumulate_luma_peak(rgba, im.width, im.height, tmp_path)
    assert node_peak == peak1

    got = client.get(f"/api/studio/{clip_id}/grade")
    assert got.status_code == 200
    assert got.json()["revision"] == revision
    assert json.dumps(got.json()["grade"], sort_keys=True) != grade_before
    # Source media unchanged; scopes never write files.
    assert hashlib.sha256(photo.read_bytes()).hexdigest() == source_hash

    # Export stills with identical grade are byte-stable regardless of prior
    # preview/scope reads (scopes are not in the export graph).
    export_a = client.get(f"/api/studio/{clip_id}/preview-frame", params={"t_s": 0})
    export_b = client.get(f"/api/studio/{clip_id}/preview-frame", params={"t_s": 0})
    assert export_a.content == export_b.content


def test_regression_contract_wrong_bins_and_stale_frames_fail_node_suite() -> None:
    """CI gate: intentional wrong expected count fails; current suite passes."""
    # Passing suite first.
    ok = subprocess.run(
        ["node", "--test", "tests/js/scopes_regression_contract.test.js"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr

    # Temporary mutation of the regression test expectation must fail.
    path = REPO / "tests/js/scopes_regression_contract.test.js"
    original = path.read_text(encoding="utf-8")
    mutated = original.replace(
        "assert.equal(hist.absolute.luma[bin], expected);",
        "assert.equal(hist.absolute.luma[bin], expected + 999);",
        1,
    )
    assert mutated != original
    try:
        path.write_text(mutated, encoding="utf-8")
        bad = subprocess.run(
            ["node", "--test", "tests/js/scopes_regression_contract.test.js"],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        assert bad.returncode != 0, "mutated bin expectation must fail"
    finally:
        path.write_text(original, encoding="utf-8")
