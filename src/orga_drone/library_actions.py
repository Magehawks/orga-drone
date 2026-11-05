"""Read-only, path-free library actions over the same queries used by Browse."""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path, PureWindowsPath
from typing import Any, TypedDict

from orga_drone.db import Database, MediaRow
from orga_drone.media_files import resolve_media_file
from orga_drone.search import media_search_from_payload


class LibraryActionError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class MediaMetadata(TypedDict):
    id: int
    kind: str
    filename: str
    available: bool
    size_bytes: int
    duration_s: float | None
    width: int | None
    height: int | None
    recorded_at: str | None
    drone_model: str | None
    camera_model: str | None
    source_type: str | None
    has_srt: bool
    has_lrf: bool
    favorite: bool
    stars: int


LIST_PARAMETERS: dict[str, dict[str, Any]] = {
    **{
        key: {"type": "string", "max_length": 512}
        for key in (
            "q",
            "ask",
            "drone",
            "date_from",
            "date_to",
        )
    },
    "kind": {"type": "string", "enum": ["video", "photo"]},
    "source": {"type": "string", "enum": ["drone", "camera", "other"]},
    "sort": {
        "type": "string",
        "enum": [
            "recorded_at",
            "filename",
            "size",
            "duration",
            "drone",
            "flow",
            "session",
            "stars",
        ],
    },
    "order": {"type": "string", "enum": ["asc", "desc"]},
    **{
        key: {"type": "boolean"}
        for key in (
            "favorite",
            "has_gps",
            "flows_only",
            "sessions_only",
        )
    },
    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
    "offset": {"type": "integer", "minimum": 0, "maximum": 1_000_000},
}


def validate_params(action: str, params: Any) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise LibraryActionError("INVALID_PARAMS")
    if action == "library.media.get":
        if params:
            raise LibraryActionError("INVALID_PARAMS")
        return {}
    if action not in {"library.media.list", "library.media.search"}:
        raise LibraryActionError("UNKNOWN_ACTION")
    if set(params) - set(LIST_PARAMETERS):
        raise LibraryActionError("INVALID_PARAMS")
    for key, value in params.items():
        spec = LIST_PARAMETERS[key]
        if spec["type"] == "boolean":
            valid = type(value) is bool
        elif spec["type"] == "integer":
            valid = type(value) is int and spec["minimum"] <= value <= spec["maximum"]
        else:
            valid = isinstance(value, str) and len(value) <= spec.get("max_length", 512)
            if "enum" in spec:
                valid = valid and value in spec["enum"]
        if not valid:
            raise LibraryActionError("INVALID_PARAMS")
        if key in {"date_from", "date_to"}:
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError
            except (ValueError, TypeError):
                raise LibraryActionError("INVALID_PARAMS") from None
    if params.get("date_from", "") > params.get("date_to", "9999-12-31"):
        raise LibraryActionError("INVALID_PARAMS")
    return dict(params)


def _number(value: Any) -> float | None:
    if type(value) not in (int, float):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def metadata(db: Database, item: MediaRow, roots: dict[int, Path]) -> MediaMetadata:
    try:
        available = resolve_media_file(db, item, roots=roots) is not None
    except (OSError, ValueError, RuntimeError):
        available = False
    return {
        "id": item.id,
        "kind": item.kind,
        "filename": PureWindowsPath(item.filename).name,
        "available": available,
        "size_bytes": max(0, item.size_bytes),
        "duration_s": _number(item.duration_s),
        "width": item.width if item.width is not None and item.width > 0 else None,
        "height": item.height if item.height is not None and item.height > 0 else None,
        "recorded_at": item.recorded_at,
        "drone_model": item.drone_model,
        "camera_model": item.camera_model,
        "source_type": item.source_type,
        "has_srt": item.has_srt,
        "has_lrf": item.has_lrf,
        "favorite": item.favorite,
        "stars": item.stars,
    }


def read_media(
    db: Database, action: str, target: dict[str, Any], params: Any
) -> dict[str, Any]:
    """No import, probing, cache generation, or filesystem writes occur here."""
    clean = validate_params(action, params)
    roots = {int(row["id"]): Path(row["path"]) for row in db.list_roots()}
    if action == "library.media.get":
        if set(target) != {"media_id"}:
            raise LibraryActionError("INVALID_TARGET")
        media_id = target["media_id"]
        if type(media_id) is not int or not 0 < media_id <= 2**53 - 1:
            raise LibraryActionError("INVALID_IDENTIFIER")
        item = db.get_media(media_id)
        if item is None or item.kind not in {"video", "photo"}:
            raise LibraryActionError("TARGET_NOT_FOUND")
        result = metadata(db, item, roots)
        if not result["available"]:
            raise LibraryActionError("MEDIA_UNAVAILABLE")
        return {"item": result}
    if target:
        raise LibraryActionError("INVALID_TARGET")
    search = media_search_from_payload(clean)
    filters: dict[str, Any] = {
        "kind": search.kind,
        "q": search.effective_q(),
        "date_from": search.date_from,
        "date_to": search.date_to,
        "favorite": search.favorite,
        **{
            key: clean.get(key)
            for key in (
                "drone",
                "source",
                "has_gps",
                "flows_only",
                "sessions_only",
            )
        },
    }
    limit, offset = clean.get("limit", 50), clean.get("offset", 0)
    items = db.list_media(
        **filters,
        sort=clean.get("sort", "recorded_at"),
        order=clean.get("order", "desc"),
        limit=limit,
        offset=offset,
    )
    return {
        "items": [metadata(db, item, roots) for item in items],
        "total": db.count_media(**filters),
        "limit": limit,
        "offset": offset,
    }
