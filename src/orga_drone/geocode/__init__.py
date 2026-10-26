"""Offline reverse geocoding with SQLite cache (rounded coordinates)."""

from __future__ import annotations

import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path
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


def _dataset_path() -> Path:
    return Path(__file__).resolve().parent / "rg_cities1000.csv"


def _field(hit: object, name: str) -> str:
    if isinstance(hit, dict):
        value = hit.get(name, "")
    else:
        value = getattr(hit, name, "")
    return str(value or "").strip()


def _geocoder() -> Any:
    """Single-process tree over the dated GeoNames CSV.

    The library's default search reads the undated wheel CSV and calls
    ``np.float``, which NumPy 2 no longer provides. Mode 1 is that library's
    single-process nearest-row query.
    """
    import numpy as np

    if not hasattr(np, "float"):
        np.float = np.float64  # type: ignore[attr-defined]
    import reverse_geocoder as rg

    cached = getattr(_geocoder, "instance", None)
    if cached is not None:
        return cached
    for cell in rg.RGeocoder.__closure__ or ():
        if isinstance(cell.cell_contents, dict):
            cell.cell_contents.clear()
    instance = rg.RGeocoder(
        mode=1,
        verbose=False,
        stream=io.StringIO(_dataset_path().read_text(encoding="utf-8")),
    )
    _geocoder.instance = instance  # type: ignore[attr-defined]
    return instance


def lookup_offline(lat: float, lon: float) -> PlaceResult | None:
    """Nearest populated place from the dated GeoNames extract."""
    try:
        hits = _geocoder().query([(lat, lon)])
    except Exception:
        return None
    if not hits:
        return None
    hit = hits[0]
    cc = _field(hit, "cc").upper() or None
    city = _field(hit, "name") or None
    region = _field(hit, "admin1") or None
    district = _field(hit, "admin2") or None
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
    place = lookup_offline(lat, lon)
    if place is not None:
        db.upsert_geocode_cache(lat_key, lon_key, place)
    return place
