"""Automatic time/place tags computed during library scan."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from orga_drone.config import settings
from orga_drone.db import tags_to_json
from orga_drone.geocode import PlaceResult, place_to_json, resolve

if TYPE_CHECKING:
    from orga_drone.db import Database


def time_tags_from_recorded_at(recorded_at: str | None) -> list[str]:
    if not recorded_at:
        return []
    text = recorded_at.strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return []
    return [f"{dt.year:04d}", f"{dt.year:04d}-{dt.month:02d}"]


def place_tags_from_result(place: PlaceResult) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()

    def add(label: str | None) -> None:
        if not label:
            return
        key = label.casefold()
        if key in seen:
            return
        seen.add(key)
        tags.append(label)

    add(place.city)
    add(place.district)
    if place.region and place.region.casefold() not in seen:
        add(place.region)
    add(place.country)
    return tags


def compute_auto_tags(
    db: Database,
    *,
    recorded_at: str | None,
    latitude: float | None,
    longitude: float | None,
    geocode_mode: str | None = None,
) -> tuple[list[str], PlaceResult | None]:
    tags = time_tags_from_recorded_at(recorded_at)
    place: PlaceResult | None = None
    mode = (geocode_mode or settings.geocode_mode).strip().lower()
    if mode != "off" and latitude is not None and longitude is not None:
        place = resolve(db, latitude, longitude, mode=mode)
        if place:
            tags.extend(place_tags_from_result(place))
    return tags, place


def apply_auto_tags_to_media(
    db: Database,
    media_id: int,
    *,
    recorded_at: str | None,
    latitude: float | None,
    longitude: float | None,
    geocode_mode: str | None = None,
) -> list[str]:
    """Recompute and persist auto tags for one media row (idempotent on rescan)."""
    tags, place = compute_auto_tags(
        db,
        recorded_at=recorded_at,
        latitude=latitude,
        longitude=longitude,
        geocode_mode=geocode_mode,
    )
    db.update_media_auto_tags(
        media_id,
        auto_tags_json=tags_to_json(tags),
        place_json=place_to_json(place),
    )
    return tags
