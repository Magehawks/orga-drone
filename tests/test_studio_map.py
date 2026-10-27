"""Flight map overlay: stored GPS, placement, and offline export (Issue #108)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.export.studio_config import StudioExportClip
from orga_drone.studio_mask import Mask
from orga_drone.export.studio_encoder import _segment_filter_invocation
from orga_drone.ffmpeg_bin import find_ffmpeg
from orga_drone.studio_image import image_adjust_from_effect_settings
from orga_drone.studio_map import (
    GAP_S,
    GpsSample,
    MapPlacement,
    axis_expr,
    box_pixels,
    default_map_box,
    dump_map,
    flight_map_overlay,
    gps_from_stored,
    map_from_effect_settings,
    marker_xy,
    osm_basemap,
    osm_tile_layout,
    parse_map_payload,
    project_route,
    render_route_image,
    route_preview,
)
from orga_drone.studio_overlay import Overlay, content_rect, overlay_box_pixels

_ROUTE = (126, 182, 255, 255)


def _seed(
    db: Database,
    root_path: Path,
    *,
    filename: str,
    kind: str,
    duration_s: float | None,
    track: list[dict[str, float]] | None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> int:
    root_path.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root_path, label="test")
    media_file = root_path / filename
    media_file.write_bytes(b"media")
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": kind,
            "filename": filename,
            "path": str(media_file.resolve()),
            "size_bytes": media_file.stat().st_size,
            "duration_s": duration_s,
            "recorded_at": "2024-06-01T12:00:00",
            "sequence": 1,
            "mode": None,
            "drone_model": "Avata 2",
            "camera_model": None,
            "latitude": latitude,
            "longitude": longitude,
            "abs_alt": None,
            "has_srt": 1 if track else 0,
            "has_lrf": 0,
            "track_json": json.dumps(track) if track else None,
        }
    )


def _add(db: Database, media_id: int) -> int:
    item = db.get_media(media_id)
    assert item is not None
    clip_id, _created = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
    )
    return clip_id


def _track() -> tuple[GpsSample, ...]:
    return (
        GpsSample(47.0, 8.0, 0.0),
        GpsSample(47.2, 8.2, 2.0),
        GpsSample(47.4, 8.4, 4.0),
    )


def test_route_projects_north_up_and_holds_gaps() -> None:
    points = project_route(_track(), media_duration_s=4.0)
    assert points[2].y < points[0].y
    assert points[2].x > points[0].x
    mid = marker_xy(points, 2.0)
    assert mid is not None
    assert mid[0] == pytest.approx(points[1].x)
    assert mid[1] == pytest.approx(points[1].y)
    gap = project_route(
        (GpsSample(47.0, 8.0, 0.0), GpsSample(48.0, 9.0, 5.0)),
        media_duration_s=5.0,
    )
    assert 5.0 > GAP_S
    assert marker_xy(gap, 2.0) == (gap[0].x, gap[0].y)
    assert marker_xy(gap, 5.0) == (gap[1].x, gap[1].y)
    assert "/" not in axis_expr([(point.t, point.x) for point in gap])
    assert "/" in axis_expr([(point.t, point.x) for point in points])


def test_missing_gps_is_empty_and_a_still_fix_is_centered() -> None:
    assert gps_from_stored(None, latitude=None, longitude=None) == ()
    assert gps_from_stored([{"lat": 0.0, "lon": 0.0}], latitude=None, longitude=None) == ()
    assert project_route((), media_duration_s=3) == ()
    preview = route_preview((), media_duration_s=3)
    assert preview["line"] == []
    assert preview["marker"] == []
    still = gps_from_stored([], latitude=47.2, longitude=8.3)
    centered = project_route(still, media_duration_s=None)
    assert centered[0].x == 0.5
    assert centered[0].y == 0.5
    assert centered[0].t == 0.0
    untimed = project_route(
        gps_from_stored(
            [{"lat": 47.0, "lon": 8.0}, {"lat": 47.1, "lon": 8.1}],
        ),
        media_duration_s=8.0,
    )
    assert untimed[0].t == 0.0
    assert untimed[1].t == 8.0


def test_placement_stays_inside_the_fitted_picture() -> None:
    parked = map_from_effect_settings(None)
    assert parked.enabled is False
    assert parked.x == pytest.approx(default_map_box(16, 9)[0])
    assert parked.opacity == pytest.approx(1)
    pushed = parse_map_payload({"enabled": True, "x": 2, "y": -1, "w": 0.99, "h": 0.01})
    assert pushed.w == pytest.approx(0.72)
    assert pushed.h == pytest.approx(0.12)
    assert pushed.x + pushed.w <= 1
    assert pushed.y + pushed.h <= 1
    with pytest.raises(ValueError, match="enabled"):
        parse_map_payload({"enabled": "yes", "x": 0.2, "y": 0.2, "w": 0.2, "h": 0.2})
    placement = MapPlacement(enabled=True, x=0.25, y=0.25, w=0.5, h=0.5)
    rect = content_rect(320, 180, 320, 180)
    overlay = Overlay(
        id="ovmapbox01",
        kind="rectangle",
        start_s=0,
        end_s=1,
        x=0.25,
        y=0.25,
        w=0.5,
        h=0.5,
    )
    assert box_pixels(placement, rect) == overlay_box_pixels(overlay, rect)
    edge = box_pixels(MapPlacement(enabled=True, x=0.9, y=0.9, w=0.4, h=0.4), rect)
    assert edge[0] >= 0 and edge[1] >= 0
    assert edge[0] + edge[2] <= 320
    assert edge[1] + edge[3] <= 180


def test_default_map_box_is_square_and_opacity_is_one_overlay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old 0.28×0.28 fractions stretch a square map on a 16:9 frame."""
    monkeypatch.setattr("orga_drone.studio_map.cached_osm_tile", lambda *_args, **_kwargs: None)
    wide_x, wide_y, wide_w, wide_h = default_map_box(1920, 1080)
    assert wide_w * 1920 == pytest.approx(wide_h * 1080, rel=0.02)
    assert wide_w * wide_h < 0.28 * 0.28
    assert wide_h == pytest.approx(0.22, abs=0.01)
    assert wide_x + wide_w <= 1
    assert wide_y + wide_h <= 1
    assert wide_x > 0.5 and wide_y > 0.5
    tall_x, _tall_y, tall_w, tall_h = default_map_box(1080, 1920)
    assert tall_w * 1080 == pytest.approx(tall_h * 1920, rel=0.02)
    assert tall_x + tall_w <= 1

    missing = map_from_effect_settings(
        '{"map":{"enabled":true,"h":0.28,"w":0.28,"x":0.68,"y":0.68}}'
    )
    assert missing.opacity == pytest.approx(1)
    stored = dump_map(
        '{"image":{"exposure":1}}',
        MapPlacement(enabled=True, x=wide_x, y=wide_y, w=wide_w, h=wide_h, opacity=0),
    )
    restored = map_from_effect_settings(stored)
    assert restored.opacity == pytest.approx(0)
    assert json.loads(stored)["image"]["exposure"] == 1
    with pytest.raises(ValueError, match="opacity"):
        parse_map_payload(
            {"enabled": True, "x": 0.2, "y": 0.2, "w": 0.2, "h": 0.2, "opacity": "half"}
        )

    _args, graph, label = flight_map_overlay(
        placement=MapPlacement(
            enabled=True, x=0.68, y=0.68, w=0.28, h=0.28, opacity=0.5
        ),
        track=_track(),
        media_duration_s=4.0,
        frame_width=1920,
        frame_height=1080,
        source_width=1920,
        source_height=1080,
        dest_dir=tmp_path,
        first_input=1,
        picture_label="pic",
        fps=30,
    )
    with Image.open(tmp_path / "flight-map-route.png") as panel:
        assert abs(panel.width - panel.height) <= 1
        assert panel.width < int(0.28 * 1920)
    assert graph.count("colorchannelmixer=aa=0.50") == 1
    assert label == "mapout"
    assert "mapjoined" in graph


def _colors(image: Image.Image) -> set[tuple[int, ...]]:
    reader = getattr(image, "get_flattened_data", None)
    pixels = reader() if reader is not None else image.getdata()
    return set(pixels)


def test_route_png_keeps_the_plain_panel_without_tiles() -> None:
    image = render_route_image(project_route(_track(), media_duration_s=4), width=160, height=100)
    assert _ROUTE in _colors(image)
    empty = render_route_image((), width=80, height=60)
    assert _ROUTE not in _colors(empty)
    assert (20, 24, 29, 255) in _colors(empty)


def test_openstreetmap_tiles_share_the_route_square(tmp_path: Path) -> None:
    samples = _track()
    preview = route_preview(samples, media_duration_s=4)
    tiles = preview["tiles"]
    assert isinstance(tiles, list) and tiles
    assert route_preview((), media_duration_s=3)["tiles"] == []
    still = gps_from_stored([], latitude=47.2, longitude=8.3)
    assert project_route(still, media_duration_s=None)[0].x == 0.5
    assert osm_tile_layout(still)

    def fail(_z: int, _x: int, _y: int) -> Path | None:
        return None

    assert osm_basemap(samples, width=80, height=60, fetch=fail) is None
    tile = tmp_path / "tile.png"
    Image.new("RGBA", (8, 8), (20, 180, 40, 255)).save(tile)

    def serve(_z: int, _x: int, _y: int) -> Path:
        return tile

    painted = osm_basemap(samples, width=160, height=100, fetch=serve)
    assert painted is not None
    image = render_route_image(
        project_route(samples, media_duration_s=4),
        width=160,
        height=100,
        background=painted,
    )
    assert (20, 180, 40, 255) in _colors(image)
    assert _ROUTE in _colors(image)
    assert "© OpenStreetMap" in Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")


def test_long_filter_script_still_draws_the_flight_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("orga_drone.studio_hud.FILTER_INLINE_LIMIT", 0)
    monkeypatch.setattr("orga_drone.studio_map.cached_osm_tile", lambda *_args, **_kwargs: None)
    still = tmp_path / "still.jpg"
    Image.new("RGB", (320, 180), (30, 40, 50)).save(still, "JPEG")
    clip = StudioExportClip(
        source_path=still,
        kind="photo",
        duration_s=2.0,
        map_placement=MapPlacement(enabled=True, x=0.6, y=0.56, w=0.28, h=0.28),
        gps_track=_track(),
        media_duration_s=4.0,
        masks=(
            Mask(id="mabc1234567", effect="blur", strength=80, x=0.2, y=0.2, w=0.3, h=0.3),
        ),
    )
    extra, filters = _segment_filter_invocation(clip, 320, 180, tmp_path)
    assert filters[0] == "-filter_complex_script"
    assert filters[-2:] == ["-map", "[vout]"]
    body = Path(filters[1]).read_text(encoding="utf-8")
    assert "flight-map-route.png" in " ".join(extra)
    assert "[vout]" in body
    from orga_drone.export.studio_encoder import _uses_filter_graph

    assert _uses_filter_graph(filters)
    assert not _uses_filter_graph(["-vf", "scale=320:180"])


def _filter_graph_text(filters: list[str]) -> str:
    if filters[0] in {"-filter_complex_script", "-filter_script:v"}:
        return Path(filters[1]).read_text(encoding="utf-8")
    return filters[1]


def test_flight_map_places_on_a_spilled_simple_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A long simple chain is written to a script file. The map must still composite it.

    Orga Drone 2.0.0 failed a 17-clip Windows export with
    "The flight map could not be placed on this clip." The first clip was a
    127s video whose telemetry HUD exceeded the inline filter limit, so ffmpeg
    received ``-filter_script:v``. The map only accepted ``-vf``.
    """
    monkeypatch.setattr("orga_drone.studio_hud.FILTER_INLINE_LIMIT", 0)
    monkeypatch.setattr("orga_drone.studio_map.cached_osm_tile", lambda *_args, **_kwargs: None)
    still = tmp_path / "still.jpg"
    Image.new("RGB", (320, 180), (30, 40, 50)).save(still, "JPEG")
    placement = MapPlacement(enabled=True, x=0.6, y=0.56, w=0.28, h=0.28)
    photo = StudioExportClip(
        source_path=still,
        kind="photo",
        duration_s=2.0,
        fade_in_s=0.2,
        map_placement=placement,
        gps_track=_track(),
        media_duration_s=4.0,
    )
    extra, filters = _segment_filter_invocation(photo, 320, 180, tmp_path)
    assert filters[0] in {"-filter_complex", "-filter_complex_script"}
    body = _filter_graph_text(filters)
    assert "flight-map-route.png" in " ".join(extra)
    assert "flight-map-marker.png" in " ".join(extra)
    assert "scale=320:180" in body
    assert body.count("fade=t=in") == 1
    assert body.rindex("fade=t=in") > body.rindex("mapout")

    plain = StudioExportClip(source_path=still, kind="photo", duration_s=2.0)
    _plain_extra, plain_filters = _segment_filter_invocation(plain, 320, 180, tmp_path)
    assert plain_filters[0] == "-filter_script:v"
    assert "flight-map" not in _filter_graph_text(plain_filters)

    slowed = StudioExportClip(
        source_path=tmp_path / "missing.mp4",
        kind="video",
        duration_s=4.0,
        source_start_s=1.0,
        source_end_s=3.0,
        playback_speed=0.5,
        fade_in_s=0.3,
        map_placement=placement,
        gps_track=_track(),
        media_duration_s=8.0,
    )
    _slow_extra, slow_filters = _segment_filter_invocation(slowed, 320, 180, tmp_path)
    slow_body = _filter_graph_text(slow_filters)
    assert "trim=start=1.000000:end=3.000000" in slow_body
    assert "setpts=2.0*PTS" in slow_body
    assert slow_body.count("fade=t=in") == 1
    assert slow_body.rindex("fade=t=in") > slow_body.rindex("mapout")

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(still),
            *extra,
            "-t",
            "0.3",
            *filters,
            "-frames:v",
            "2",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")


def test_export_graph_draws_the_marker_before_fades(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("orga_drone.studio_map.cached_osm_tile", lambda *_args, **_kwargs: None)
    still = tmp_path / "still.jpg"
    Image.new("RGB", (320, 180), (30, 40, 50)).save(still, "JPEG")
    clip = StudioExportClip(
        source_path=still,
        kind="photo",
        duration_s=2.0,
        fade_in_s=0.2,
        map_placement=MapPlacement(enabled=True, x=0.6, y=0.56, w=0.28, h=0.28),
        gps_track=_track(),
        media_duration_s=4.0,
        overlays=(
            Overlay(
                id="ovrect0001",
                kind="rectangle",
                start_s=0.0,
                end_s=2.0,
                x=0.1,
                y=0.1,
                w=0.2,
                h=0.2,
            ),
        ),
    )
    extra, filters = _segment_filter_invocation(clip, 320, 180, tmp_path)
    assert filters[0] == "-filter_complex"
    graph = filters[1]
    joined = " ".join(extra)
    assert "flight-map-route.png" in joined
    assert "flight-map-marker.png" in joined
    assert "http://" not in graph and "https://" not in graph
    assert "if(lt(t\\," in graph
    assert graph.rindex("fade=t=in") > graph.rindex("mapout")
    off = StudioExportClip(
        source_path=still,
        kind="photo",
        duration_s=2.0,
        map_placement=MapPlacement(enabled=False),
    )
    off_extra, off_filters = _segment_filter_invocation(off, 320, 180, tmp_path)
    assert off_filters[0] == "-vf"
    assert "flight-map" not in " ".join(off_extra)

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(still),
            *extra,
            "-t",
            "0.3",
            *filters,
            "-frames:v",
            "2",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")


def test_map_persists_with_other_settings_and_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    video_id = _add(
        db,
        _seed(
            db,
            tmp_path / "lib",
            filename="DJI_0001.MP4",
            kind="video",
            duration_s=6.0,
            track=[
                {"lat": 47.1, "lon": 8.2, "t": 0.0},
                {"lat": 47.2, "lon": 8.3, "t": 3.0},
                {"lat": 47.3, "lon": 8.4, "t": 6.0},
            ],
        ),
    )
    photo_id = _add(
        db,
        _seed(
            db,
            tmp_path / "plain",
            filename="nogps.JPG",
            kind="photo",
            duration_s=None,
            track=None,
        ),
    )
    client = TestClient(app)
    page = client.get("/studio")
    assert page.status_code == 200
    assert 'id="inspector-map"' in page.text
    assert 'id="map-opacity"' in page.text
    assert 'id="studio-preview-map"' in page.text
    assert ("Flugkarte" in page.text) or ("Flight map" in page.text)
    assert ("Für diesen Clip ist kein GPS vorhanden." in page.text) or (
        "No GPS for this clip." in page.text
    )
    preview = route_preview(
        gps_from_stored(
            [
                {"lat": 47.1, "lon": 8.2, "t": 0.0},
                {"lat": 47.2, "lon": 8.3, "t": 3.0},
                {"lat": 47.3, "lon": 8.4, "t": 6.0},
            ]
        ),
        media_duration_s=6.0,
    )
    line = preview["line"]
    assert isinstance(line, list) and line
    assert str(line[0]["x"]) in page.text
    assert '"line": []' in page.text or '"line":[]' in page.text
    script = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    assert "drawFlightMap" in script
    assert "mapWrap.hidden = !(isPhoto || isVideo)" in script

    rejected = client.patch(f"/api/studio/{video_id}/map", json={"enabled": "yes"})
    assert rejected.status_code == 400
    saved = client.patch(
        f"/api/studio/{video_id}/map",
        json={"enabled": True, "x": 0.2, "y": 0.3, "w": 0.3, "h": 0.24, "opacity": 0.5},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["map"]["enabled"] is True
    assert body["map"]["x"] == pytest.approx(0.2)
    assert body["map"]["opacity"] == pytest.approx(0.5)
    graded = db.set_studio_image_adjust(video_id, {"exposure": 12})
    assert map_from_effect_settings(graded.effect_settings).enabled is True
    assert image_adjust_from_effect_settings(graded.effect_settings).exposure == 12
    left, right = db.cut_studio_video_item(video_id, 2.0)
    assert map_from_effect_settings(left.effect_settings).y == pytest.approx(0.3)
    assert map_from_effect_settings(right.effect_settings).enabled is True
    empty = client.patch(
        f"/api/studio/{photo_id}/map",
        json={"enabled": True, "x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2},
    )
    assert empty.status_code == 200
    card = db.add_studio_title_card(db.list_studio_projects()[0].id, title_text="Hi")
    blocked = client.patch(
        f"/api/studio/{card.id}/map",
        json={"enabled": True, "x": 0.2, "y": 0.2, "w": 0.2, "h": 0.2},
    )
    assert blocked.status_code == 400
