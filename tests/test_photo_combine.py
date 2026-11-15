"""Image Composer (#453): geometry, admission, export, metadata, UI entry."""

from __future__ import annotations

import io
import threading
import time
from pathlib import Path

import pytest
from PIL import Image
from PIL.ExifTags import Base

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.export.studio_encoder import StudioExportError
from orga_drone.photo_combine import (
    MAX_EDGE,
    MAX_OUTPUT_PIXELS,
    CombineEntrySpec,
    CombineSpec,
    compute_geometry,
    export_combine,
    inspect_sources,
    parse_combine_payload,
    render_preview_png,
    require_combine_ready,
)


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prefs = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr("orga_drone.app_prefs.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_export.settings", prefs)
    monkeypatch.setattr("orga_drone.config.settings", prefs)


def _add_photo(db: Database, root: Path, name: str, path: Path) -> int:
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label=root.name)
    return db.upsert_media(
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


def _rgb(path: Path, size: tuple[int, int], color: tuple[int, int, int], *, fmt: str = "PNG") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format=fmt)


def _rgba(path: Path, size: tuple[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", size, (10, 20, 30, 128))
    img.save(path, format="PNG")


def _spec(*media_ids: int, layout: str = "horizontal", spacing: int = 0, background: str = "white", fmt: str = "png") -> CombineSpec:
    entries = tuple(
        CombineEntrySpec(entry_id=f"e{i+1}", media_id=mid) for i, mid in enumerate(media_ids)
    )
    return CombineSpec(
        entries=entries,
        layout=layout,
        spacing=spacing,
        background=background,
        format=fmt,
        revision=1,
    )


def test_parse_allows_draft_one_entry_but_ready_requires_two() -> None:
    one = parse_combine_payload(
        {
            "entries": [{"entry_id": "a", "media_id": 1}],
            "layout": "horizontal",
            "spacing": 0,
            "background": "white",
            "format": "png",
        }
    )
    assert len(one.entries) == 1
    with pytest.raises(StudioExportError, match="more image"):
        require_combine_ready(one)
    with pytest.raises(StudioExportError, match="transparent"):
        parse_combine_payload(
            {
                "entries": [
                    {"entry_id": "a", "media_id": 1},
                    {"entry_id": "b", "media_id": 2},
                ],
                "layout": "horizontal",
                "spacing": 0,
                "background": "transparent",
                "format": "jpeg",
            }
        )


def test_geometry_horizontal_and_vertical_centering() -> None:
    from orga_drone.photo_combine import InspectedSource

    sources = (
        InspectedSource("a", 1, Path("a"), 100, 40, 1, 1, "a.png"),
        InspectedSource("b", 2, Path("b"), 60, 80, 1, 1, "b.png"),
    )
    h = compute_geometry(sources, layout="horizontal", spacing=10, background="white", fmt="png")
    assert h.width == 100 + 10 + 60
    assert h.height == 80
    assert h.placements[0].x == 0 and h.placements[0].y == (80 - 40) // 2
    assert h.placements[1].x == 110 and h.placements[1].y == 0

    v = compute_geometry(sources, layout="vertical", spacing=4, background="white", fmt="png")
    assert v.width == 100
    assert v.height == 40 + 4 + 80
    assert v.placements[0].x == 0 and v.placements[0].y == 0
    assert v.placements[1].x == (100 - 60) // 2 and v.placements[1].y == 44


def test_horizontal_export_order_and_spacing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    root = tmp_path / "media"
    a = root / "a.png"
    b = root / "b.png"
    c = root / "c.png"
    _rgb(a, (40, 20), (255, 0, 0))
    _rgb(b, (40, 20), (0, 255, 0))
    _rgb(c, (40, 20), (0, 0, 255))
    ids = [
        _add_photo(db, root, "a.png", a),
        _add_photo(db, root, "b.png", b),
        _add_photo(db, root, "c.png", c),
    ]
    originals = {p: p.read_bytes() for p in (a, b, c)}
    dest = tmp_path / "out.png"
    result = export_combine(db, _spec(*ids, spacing=5), dest)
    assert result.is_file()
    with Image.open(result) as img:
        assert img.size == (40 * 3 + 5 * 2, 20)
        # Left / middle / right samples stay distinct primary colors.
        assert img.getpixel((10, 10))[:3] == (255, 0, 0)
        assert img.getpixel((55, 10))[:3] == (0, 255, 0)
        assert img.getpixel((100, 10))[:3] == (0, 0, 255)
    for path, raw in originals.items():
        assert path.read_bytes() == raw


def test_many_small_images_horizontal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    root = tmp_path / "media"
    ids = []
    for i in range(12):
        p = root / f"n{i}.png"
        _rgb(p, (8, 8), (i * 10 % 255, 40, 80))
        ids.append(_add_photo(db, root, p.name, p))
    # Repeat first id to prove duplicate media ids are allowed.
    entries = [CombineEntrySpec(entry_id=f"e{i}", media_id=mid) for i, mid in enumerate(ids)]
    entries.append(CombineEntrySpec(entry_id="dup", media_id=ids[0]))
    spec = CombineSpec(
        entries=tuple(entries),
        layout="horizontal",
        spacing=0,
        background="white",
        format="png",
    )
    out = export_combine(db, spec, tmp_path / "many.png")
    with Image.open(out) as img:
        assert img.size == (8 * 13, 8)


def test_png_alpha_and_jpeg_background(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    root = tmp_path / "media"
    a = root / "a.png"
    b = root / "b.png"
    _rgba(a, (30, 20))
    _rgba(b, (20, 40))
    ids = [_add_photo(db, root, "a.png", a), _add_photo(db, root, "b.png", b)]
    png = export_combine(
        db, _spec(*ids, layout="horizontal", background="transparent", fmt="png"), tmp_path / "t.png"
    )
    with Image.open(png) as img:
        rgba = img.convert("RGBA")
        assert rgba.size == (50, 40)
        # Centering margin above the shorter first tile stays fully transparent.
        assert rgba.getpixel((5, 0))[3] == 0
        # Semi-transparent source alpha is preserved (not multiplied twice).
        assert rgba.getpixel((5, 15))[3] == 128

    jpg = export_combine(
        db, _spec(*ids, layout="vertical", background="black", fmt="jpeg"), tmp_path / "t.jpg"
    )
    with Image.open(jpg) as img:
        assert img.format == "JPEG"
        assert img.mode == "RGB"
        assert img.size == (30, 60)
        # Narrower second tile is centered on black.
        assert img.getpixel((0, 50)) == (0, 0, 0)


def test_exif_orientation_applied_before_geometry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    root = tmp_path / "media"
    # Orientation 6: 90 CW — stored 40x20 becomes 20x40 after transpose.
    path = root / "rot.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    exif = Image.Exif()
    exif[Base.Orientation] = 6
    Image.new("RGB", (40, 20), (90, 10, 10)).save(path, format="JPEG", quality=90, exif=exif)
    other = root / "other.png"
    _rgb(other, (20, 40), (10, 90, 10))
    ids = [_add_photo(db, root, "rot.jpg", path), _add_photo(db, root, "other.png", other)]
    sources = inspect_sources(db, _spec(*ids))
    assert sources[0].width == 20 and sources[0].height == 40
    out = export_combine(db, _spec(*ids, layout="horizontal"), tmp_path / "orient.png")
    with Image.open(out) as img:
        assert img.size == (40, 40)


def test_output_strips_source_exif_gps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    root = tmp_path / "media"
    a = root / "gps.jpg"
    b = root / "b.jpg"
    a.parent.mkdir(parents=True, exist_ok=True)
    exif = Image.Exif()
    exif[Base.GPSInfo] = {
        0: b"\x02\x02\x00\x00",
        1: "N",
        2: (1, 1, 1),
        3: "E",
        4: (1, 1, 1),
    }
    Image.new("RGB", (64, 48), (1, 2, 3)).save(a, format="JPEG", quality=90, exif=exif)
    _rgb(b, (64, 48), (4, 5, 6), fmt="JPEG")
    ids = [_add_photo(db, root, "gps.jpg", a), _add_photo(db, root, "b.jpg", b)]
    out = export_combine(db, _spec(*ids, fmt="jpeg"), tmp_path / "clean.jpg")
    raw = out.read_bytes()
    assert b"GPSLatitude" not in raw
    with Image.open(out) as img:
        assert not img.getexif().get(Base.GPSInfo)


def test_resource_limits_refuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from orga_drone.photo_combine import InspectedSource

    huge = (
        InspectedSource("a", 1, Path("a"), MAX_EDGE, 10, 1, 1, "a.png"),
        InspectedSource("b", 2, Path("b"), MAX_EDGE, 10, 1, 1, "b.png"),
    )
    plan = compute_geometry(huge, layout="horizontal", spacing=0, background="white", fmt="png")
    assert plan.constraint in {"edge", "area", "memory"}
    with pytest.raises(StudioExportError):
        from orga_drone.photo_combine import refuse_if_unsafe

        refuse_if_unsafe(plan)

    # Area overflow via many wide tiles
    tiles = tuple(
        InspectedSource(f"e{i}", i, Path(str(i)), 5000, 5000, 1, 1, f"{i}.png")
        for i in range(1, 6)
    )
    plan2 = compute_geometry(tiles, layout="horizontal", spacing=0, background="white", fmt="png")
    assert plan2.width * plan2.height > MAX_OUTPUT_PIXELS or plan2.constraint is not None


def test_preview_is_bounded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    root = tmp_path / "media"
    a = root / "a.png"
    b = root / "b.png"
    _rgb(a, (900, 600), (1, 2, 3))
    _rgb(b, (900, 600), (4, 5, 6))
    ids = [_add_photo(db, root, "a.png", a), _add_photo(db, root, "b.png", b)]
    data = render_preview_png(db, _spec(*ids))
    with Image.open(io.BytesIO(data)) as img:
        assert max(img.size) <= 1280


def test_inspect_and_http_export_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fastapi.testclient import TestClient

    from orga_drone.app import create_app

    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    app = create_app()
    db: Database = app.state.db
    root = tmp_path / "media"
    a = root / "a.png"
    b = root / "b.png"
    _rgb(a, (50, 40), (200, 10, 10))
    _rgb(b, (30, 60), (10, 200, 10))
    ids = [_add_photo(db, root, "a.png", a), _add_photo(db, root, "b.png", b)]
    originals = {a: a.read_bytes(), b: b.read_bytes()}

    client = TestClient(app)
    payload = {
        "entries": [
            {"entry_id": "e1", "media_id": ids[0]},
            {"entry_id": "e2", "media_id": ids[1]},
        ],
        "layout": "vertical",
        "spacing": 2,
        "background": "white",
        "format": "png",
        "revision": 1,
    }
    inspect = client.post("/api/photo-combine/inspect", json=payload)
    assert inspect.status_code == 200
    body = inspect.json()
    assert body["ok"] is True
    assert body["width"] == 50
    assert body["height"] == 40 + 2 + 60

    preview = client.post("/api/photo-combine/preview", json=payload)
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/png")

    out = tmp_path / "exports" / "combo.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    started = client.post(
        "/api/photo-combine/export",
        json={**payload, "output_path": str(out)},
    )
    assert started.status_code == 200
    job_id = started.json()["job_id"]
    final = None
    for _ in range(80):
        status = client.get(f"/api/studio/export/jobs/{job_id}")
        assert status.status_code == 200
        final = status.json()
        if final["state"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.05)
    assert final is not None
    assert final["state"] == "completed"
    result = Path(final["output_path"])
    assert result.is_file()
    with Image.open(result) as img:
        assert img.size == (50, 102)
    assert a.read_bytes() == originals[a]
    assert b.read_bytes() == originals[b]


def test_preview_coordinator_supersedes_older_claims() -> None:
    from orga_drone.photo_combine import CombinePreviewCoordinator

    gate = CombinePreviewCoordinator()
    first_seq, first_cancel = gate.claim()
    assert gate.is_current(first_seq)
    assert not first_cancel.is_set()
    second_seq, second_cancel = gate.claim()
    assert first_cancel.is_set()
    assert not second_cancel.is_set()
    assert not gate.is_current(first_seq)
    assert gate.is_current(second_seq)
    gate.release(second_cancel)
    assert gate._cancel is None  # noqa: SLF001


def test_render_preview_respects_cancel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from orga_drone.export.studio_encoder import ExportCancelled

    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    root = tmp_path / "media"
    a = root / "a.png"
    b = root / "b.png"
    _rgb(a, (40, 30), (1, 2, 3))
    _rgb(b, (40, 30), (4, 5, 6))
    ids = [_add_photo(db, root, "a.png", a), _add_photo(db, root, "b.png", b)]
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ExportCancelled):
        render_preview_png(db, _spec(*ids), cancel_event=cancel)


def test_external_and_library_sources_combine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    root = tmp_path / "media"
    lib = root / "lib.png"
    outside = tmp_path / "outside" / "desk.jpg"
    _rgb(lib, (40, 30), (200, 10, 10))
    _rgb(outside, (20, 30), (10, 200, 10), fmt="JPEG")
    mid = _add_photo(db, root, "lib.png", lib)
    with db.connect() as conn:
        before_count = int(conn.execute("SELECT COUNT(*) AS n FROM media").fetchone()["n"])
    originals = {lib: lib.read_bytes(), outside: outside.read_bytes()}

    payload = parse_combine_payload(
        {
            "entries": [
                {"entry_id": "e1", "media_id": mid},
                {"entry_id": "e2", "source_path": str(outside)},
                {"entry_id": "e3", "source_path": str(outside)},
            ],
            "layout": "horizontal",
            "spacing": 0,
            "background": "white",
            "format": "png",
        }
    )
    sources = inspect_sources(db, payload)
    assert len(sources) == 3
    assert sources[0].external is False
    assert sources[1].external is True
    assert sources[2].path == sources[1].path

    out = export_combine(db, payload, tmp_path / "mixed.png")
    with Image.open(out) as img:
        assert img.size == (80, 30)
    assert lib.read_bytes() == originals[lib]
    assert outside.read_bytes() == originals[outside]
    with db.connect() as conn:
        after_count = int(conn.execute("SELECT COUNT(*) AS n FROM media").fetchone()["n"])
    assert after_count == before_count


def test_reject_unsupported_external_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    root = tmp_path / "media"
    a = root / "a.png"
    bad = tmp_path / "note.txt"
    _rgb(a, (20, 20), (1, 2, 3))
    bad.write_text("nope", encoding="utf-8")
    mid = _add_photo(db, root, "a.png", a)
    spec = parse_combine_payload(
        {
            "entries": [
                {"entry_id": "e1", "media_id": mid},
                {"entry_id": "e2", "source_path": str(bad)},
            ],
            "layout": "horizontal",
            "spacing": 0,
            "background": "white",
            "format": "png",
        }
    )
    with pytest.raises(StudioExportError, match="not supported"):
        inspect_sources(db, spec)


def test_detail_page_shows_combine_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fastapi.testclient import TestClient

    from orga_drone.app import create_app
    from orga_drone.i18n import clear_catalog_cache

    clear_catalog_cache()
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    app = create_app()
    db: Database = app.state.db
    root = tmp_path / "media"
    photo = root / "shot.png"
    _rgb(photo, (80, 60), (8, 9, 10))
    mid = _add_photo(db, root, "shot.png", photo)
    client = TestClient(app)
    page = client.get(f"/media/{mid}", cookies={"lang": "en"})
    assert page.status_code == 200
    text = page.text
    assert 'id="detail-photo-combine-open"' in text
    assert "Combine images" in text
    assert 'id="detail-photo-combine-dialog"' in text
    assert 'id="detail-photo-combine-from-library"' in text
    assert 'id="detail-photo-combine-from-computer"' in text
    assert 'id="detail-photo-combine-library-dialog"' in text
    assert 'id="detail-photo-combine-search"' not in text
    assert "From library" in text
    assert "From this computer" in text
    assert "/static/js/photo-combine.js" in text
    image = text.split('id="detail-panel-image"', 1)[1].split('id="detail-panel-export"', 1)[0]
    assert 'id="detail-photo-combine-open"' in image
    assert 'id="detail-export-run"' not in image

    german = client.get(f"/media/{mid}", cookies={"lang": "de"})
    assert "Fotos zusammenfügen" in german.text
    assert "Aus der Mediathek" in german.text
    assert "Von diesem Computer" in german.text
