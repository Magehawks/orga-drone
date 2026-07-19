"""Build a privacy-minded GeoJSON spot export for one media item.

Coordinates are rounded (default 4 decimal places, ≈11 m) so the exact
home/takeoff point is not exported. Nothing is uploaded — download only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orga_drone.db import MediaRow

SPOT_VERSION = 1
# ~11 m at the equator; enough for MVP privacy without inventing a fake location.
COORD_DECIMALS = 4
MAX_TRACK_POINTS = 200


def round_coord(value: float, decimals: int = COORD_DECIMALS) -> float:
    return round(float(value), decimals)


def downsample_track(
    points: list[dict[str, Any]],
    max_points: int = MAX_TRACK_POINTS,
) -> list[dict[str, Any]]:
    """Keep first/last and evenly sample the rest when the track is long."""
    n = len(points)
    if n <= max_points or max_points < 2:
        return list(points)
    if max_points == 2:
        return [points[0], points[-1]]
    inner = max_points - 2
    step = (n - 1) / (inner + 1)
    indices = [0]
    for i in range(1, inner + 1):
        indices.append(int(round(i * step)))
    indices.append(n - 1)
    # Deduplicate while preserving order (rounding can collide).
    seen: set[int] = set()
    out: list[dict[str, Any]] = []
    for idx in indices:
        if idx not in seen:
            seen.add(idx)
            out.append(points[idx])
    if out[-1] is not points[-1]:
        out.append(points[-1])
    return out


def _track_linestring_coords(track: list[dict[str, Any]]) -> list[list[float]]:
    coords: list[list[float]] = []
    for p in downsample_track(track):
        lat = p.get("lat")
        lon = p.get("lon")
        if lat is None or lon is None:
            continue
        try:
            coords.append([round_coord(float(lon)), round_coord(float(lat))])
        except (TypeError, ValueError):
            continue
    return coords


def spot_download_filename(filename: str) -> str:
    stem = Path(filename).stem or "spot"
    # Avoid path separators / quotes in Content-Disposition filenames.
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in stem)
    return f"{safe or 'spot'}.orga-spot.json"


def build_spot_geojson(
    item: MediaRow,
    track: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a GeoJSON FeatureCollection for local download.

    Raises ValueError if latitude/longitude are missing.
    """
    if item.latitude is None or item.longitude is None:
        raise ValueError("GPS coordinates required for spot export")

    lon = round_coord(item.longitude)
    lat = round_coord(item.latitude)
    title = Path(item.filename).stem or item.filename

    properties: dict[str, Any] = {
        "title": title,
        "filename": item.filename,
        "recorded_at": item.recorded_at,
        "drone_model": item.drone_model,
        "notes": item.notes or "",
        "tags": list(item.tags or []),
        "kind": item.kind,
        "orga_drone_spot_version": SPOT_VERSION,
        "coord_decimals": COORD_DECIMALS,
        "privacy": (
            f"Coordinates rounded to {COORD_DECIMALS} decimal places "
            "(≈11 m) — exact home location is not exported."
        ),
    }

    features: list[dict[str, Any]] = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat],
            },
            "properties": {
                **properties,
                "role": "spot",
            },
        }
    ]

    line = _track_linestring_coords(track or [])
    if len(line) >= 2:
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": line,
                },
                "properties": {
                    "role": "track",
                    "title": title,
                    "filename": item.filename,
                    "orga_drone_spot_version": SPOT_VERSION,
                    "coord_decimals": COORD_DECIMALS,
                    "point_count": len(line),
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "orga_drone_spot_version": SPOT_VERSION,
        "features": features,
    }
