"""Offline reverse geocoding with SQLite cache (rounded coordinates)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from orga_drone.geocode.countries import country_name

if TYPE_CHECKING:
    from orga_drone.db import Database

COORD_DECIMALS = 3
SOURCE_OFFLINE = "reverse_geocoder"


@dataclass
class PlaceResult:
    country: str | None
    region: str | None
    city: str | None
    district: str | None
    country_code: str | None
    source: str = SOURCE_OFFLINE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PlaceResult | None:
        if not data:
            return None
        return cls(
            country=data.get("country"),
            region=data.get("region"),
            city=data.get("city"),
            district=data.get("district"),
            country_code=data.get("country_code"),
            source=str(data.get("source") or SOURCE_OFFLINE),
        )


def round_coord(value: float, decimals: int = COORD_DECIMALS) -> float:
    return round(float(value), decimals)


def place_to_json(place: PlaceResult | None) -> str | None:
    if place is None:
        return None
    return json.dumps(place.to_dict(), ensure_ascii=False)


def place_from_json(raw: str | None) -> PlaceResult | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return PlaceResult.from_dict(data)


def _lookup_offline(lat: float, lon: float) -> PlaceResult | None:
    try:
        import reverse_geocoder as rg
    except ImportError:
        return None
    try:
        hits = rg.search((lat, lon))
    except Exception:
        return None
    if not hits:
        return None
    hit = hits[0]
    cc = str(getattr(hit, "cc", "") or "").upper() or None
    city = str(getattr(hit, "name", "") or "").strip() or None
    region = str(getattr(hit, "admin1", "") or "").strip() or None
    district = str(getattr(hit, "admin2", "") or "").strip() or None
    if district and city and district.casefold() == city.casefold():
        district = None
    return PlaceResult(
        country=country_name(cc),
        region=region,
        city=city,
        district=district,
        country_code=cc,
        source=SOURCE_OFFLINE,
    )


def resolve(
    db: Database,
    lat: float,
    lon: float,
    *,
    mode: str = "offline",
) -> PlaceResult | None:
    """Resolve coordinates to a place (offline by default, DB-cached)."""
    if mode == "off":
        return None
    lat_key = round_coord(lat)
    lon_key = round_coord(lon)
    cached = db.get_geocode_cache(lat_key, lon_key)
    if cached is not None:
        return cached
    if mode != "offline":
        return None
    place = _lookup_offline(lat, lon)
    if place is not None:
        db.upsert_geocode_cache(lat_key, lon_key, place)
    return place
