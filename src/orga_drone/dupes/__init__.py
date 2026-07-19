"""Likely-duplicate detection across library roots (no content hashing).

MVP fingerprint (either match is enough):

1. **DJI stem** — case-insensitive filename stem matching the DJI pattern
   ``DJI_YYYYMMDDHHMMSS_NNNN_M`` (same clip name on SD + backup).
2. **Attributes** — same filename (casefold) + exact ``size_bytes``, plus
   ``recorded_at`` within ±``RECORDED_AT_TOLERANCE_S`` and ``duration_s``
   within ±``DURATION_TOLERANCE_S``. If both sides lack duration or
   recorded_at, that field still passes; if only one side has a value, it
   does not block the match.

Thresholds (documented for operators / tests):

- ``RECORDED_AT_TOLERANCE_S`` = 2.0 seconds
- ``DURATION_TOLERANCE_S`` = 1.0 second
- ``size_bytes`` must match exactly (byte-identical copies)

Never deletes files — detection and navigation only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from orga_drone.parse import DJI_NAME_RE

# --- Documented MVP thresholds ------------------------------------------------
RECORDED_AT_TOLERANCE_S = 2.0
DURATION_TOLERANCE_S = 1.0


@dataclass(frozen=True)
class MediaFingerprintInput:
    id: int
    root_id: int
    filename: str
    path: str
    size_bytes: int
    duration_s: float | None
    recorded_at: str | None
    kind: str = "video"
    root_label: str | None = None
    root_path: str | None = None


@dataclass
class DuplicateMember:
    id: int
    root_id: int
    filename: str
    path: str
    size_bytes: int
    duration_s: float | None
    recorded_at: str | None
    kind: str
    root_label: str | None = None
    root_path: str | None = None


@dataclass
class DuplicateGroup:
    key: str
    match_reasons: list[str] = field(default_factory=list)
    members: list[DuplicateMember] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.members)


def normalize_dji_stem(filename: str) -> str | None:
    """Return uppercased DJI stem (no extension) or None if not a DJI name."""
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    match = DJI_NAME_RE.match(name)
    if not match:
        return None
    return name.rsplit(".", 1)[0].upper()


def _parse_recorded(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def recorded_within_tolerance(
    a: str | None,
    b: str | None,
    *,
    tolerance_s: float = RECORDED_AT_TOLERANCE_S,
) -> bool:
    """True if both missing, one missing, or both parse and |Δ| ≤ tolerance."""
    da, db = _parse_recorded(a), _parse_recorded(b)
    if da is None or db is None:
        return True
    return abs((da - db).total_seconds()) <= tolerance_s


def duration_within_tolerance(
    a: float | None,
    b: float | None,
    *,
    tolerance_s: float = DURATION_TOLERANCE_S,
) -> bool:
    if a is None or b is None:
        return True
    return abs(float(a) - float(b)) <= tolerance_s


def attributes_match(
    a: MediaFingerprintInput,
    b: MediaFingerprintInput,
    *,
    recorded_tol_s: float = RECORDED_AT_TOLERANCE_S,
    duration_tol_s: float = DURATION_TOLERANCE_S,
) -> bool:
    if a.filename.casefold() != b.filename.casefold():
        return False
    if int(a.size_bytes) != int(b.size_bytes):
        return False
    if not recorded_within_tolerance(a.recorded_at, b.recorded_at, tolerance_s=recorded_tol_s):
        return False
    if not duration_within_tolerance(a.duration_s, b.duration_s, tolerance_s=duration_tol_s):
        return False
    return True


class _UnionFind:
    def __init__(self) -> None:
        self._parent: dict[int, int] = {}
        self._reasons: dict[int, set[str]] = {}

    def add(self, x: int) -> None:
        if x not in self._parent:
            self._parent[x] = x
            self._reasons[x] = set()

    def find(self, x: int) -> int:
        self.add(x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: int, b: int, reason: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            self._reasons.setdefault(ra, set()).add(reason)
            return
        self._parent[rb] = ra
        merged = self._reasons.setdefault(ra, set())
        merged.update(self._reasons.pop(rb, set()))
        merged.add(reason)


def find_duplicate_groups(
    items: Iterable[MediaFingerprintInput],
    *,
    recorded_tol_s: float = RECORDED_AT_TOLERANCE_S,
    duration_tol_s: float = DURATION_TOLERANCE_S,
) -> list[DuplicateGroup]:
    """Return groups of 2+ media that look like the same clip (different paths)."""
    by_id: dict[int, MediaFingerprintInput] = {item.id: item for item in items}
    if len(by_id) < 2:
        return []

    uf = _UnionFind()
    for mid in by_id:
        uf.add(mid)

    # 1) DJI stem buckets
    stem_buckets: dict[str, list[int]] = {}
    for mid, item in by_id.items():
        stem = normalize_dji_stem(item.filename)
        if stem:
            stem_buckets.setdefault(stem, []).append(mid)

    for ids in stem_buckets.values():
        if len(ids) < 2:
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = by_id[ids[i]], by_id[ids[j]]
                if a.path == b.path:
                    continue
                uf.union(ids[i], ids[j], "dji_stem")

    # 2) Attribute buckets: filename + size, then pairwise tolerance
    attr_buckets: dict[tuple[str, int], list[int]] = {}
    for mid, item in by_id.items():
        key = (item.filename.casefold(), int(item.size_bytes))
        attr_buckets.setdefault(key, []).append(mid)

    for ids in attr_buckets.values():
        if len(ids) < 2:
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = by_id[ids[i]], by_id[ids[j]]
                if a.path == b.path:
                    continue
                if attributes_match(
                    a,
                    b,
                    recorded_tol_s=recorded_tol_s,
                    duration_tol_s=duration_tol_s,
                ):
                    uf.union(ids[i], ids[j], "attributes")

    components: dict[int, list[int]] = {}
    for mid in by_id:
        components.setdefault(uf.find(mid), []).append(mid)

    groups: list[DuplicateGroup] = []
    for root, member_ids in components.items():
        match_reasons = sorted(uf._reasons.get(root, set()))
        if not match_reasons:
            continue
        paths = {by_id[m].path for m in member_ids}
        if len(paths) < 2:
            continue
        members = [
            DuplicateMember(
                id=by_id[m].id,
                root_id=by_id[m].root_id,
                filename=by_id[m].filename,
                path=by_id[m].path,
                size_bytes=by_id[m].size_bytes,
                duration_s=by_id[m].duration_s,
                recorded_at=by_id[m].recorded_at,
                kind=by_id[m].kind,
                root_label=by_id[m].root_label,
                root_path=by_id[m].root_path,
            )
            for m in sorted(member_ids, key=lambda i: (by_id[i].root_id, by_id[i].path))
        ]
        groups.append(
            DuplicateGroup(
                key=f"dup-{root}",
                match_reasons=match_reasons,
                members=members,
            )
        )

    groups.sort(
        key=lambda g: (
            -g.size,
            g.members[0].recorded_at or "",
            g.members[0].filename.casefold(),
        )
    )
    return groups


def media_row_to_fingerprint(
    row: Any,
    *,
    root_label: str | None = None,
    root_path: str | None = None,
) -> MediaFingerprintInput:
    """Build fingerprint input from sqlite Row / mapping / MediaRow-like object."""
    if hasattr(row, "keys"):
        keys = set(row.keys())
        return MediaFingerprintInput(
            id=int(row["id"]),
            root_id=int(row["root_id"]),
            filename=row["filename"],
            path=row["path"],
            size_bytes=int(row["size_bytes"] or 0),
            duration_s=row["duration_s"],
            recorded_at=row["recorded_at"],
            kind=row["kind"],
            root_label=root_label
            or (row["root_label"] if "root_label" in keys else None),
            root_path=root_path or (row["root_path"] if "root_path" in keys else None),
        )
    return MediaFingerprintInput(
        id=int(row.id),
        root_id=int(row.root_id),
        filename=row.filename,
        path=row.path,
        size_bytes=int(row.size_bytes or 0),
        duration_s=row.duration_s,
        recorded_at=row.recorded_at,
        kind=row.kind,
        root_label=root_label,
        root_path=root_path,
    )


__all__ = [
    "RECORDED_AT_TOLERANCE_S",
    "DURATION_TOLERANCE_S",
    "MediaFingerprintInput",
    "DuplicateMember",
    "DuplicateGroup",
    "normalize_dji_stem",
    "recorded_within_tolerance",
    "duration_within_tolerance",
    "attributes_match",
    "find_duplicate_groups",
    "media_row_to_fingerprint",
]
