"""Central local LUT catalog on top of ``studio_lut`` file storage.

Keeps ``{data_dir}/luts/{32hex}.cube`` filenames for clip compatibility.
Metadata (display name, SHA-256, import time) lives in SQLite ``lut_assets``.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from orga_drone.studio_lut import (
    LUT_NAME_RE,
    LutInvalidError,
    LutMissingError,
    TITLE_RE,
    color_look_from_effect_settings,
    lut_asset_dir,
    require_lut_asset,
    resolve_lut_asset,
    validate_cube_bytes,
)

if TYPE_CHECKING:
    from orga_drone.db import Database

MAX_DISPLAY_NAME_LEN = 80
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f<>:\"|?*]")


@dataclass(frozen=True)
class LutUsage:
    clip_count: int = 0
    project_count: int = 0
    project_titles: tuple[str, ...] = ()


@dataclass(frozen=True)
class LutCatalogEntry:
    asset_name: str
    display_name: str
    content_sha256: str
    imported_at: str
    file_present: bool
    usage: LutUsage = field(default_factory=LutUsage)

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["usage"] = {
            "clip_count": self.usage.clip_count,
            "project_count": self.usage.project_count,
            "project_titles": list(self.usage.project_titles),
        }
        return data


@dataclass(frozen=True)
class LutImportResult:
    entry: LutCatalogEntry
    already_present: bool = False
    restored: bool = False

    def as_dict(self) -> dict[str, object]:
        payload = self.entry.as_dict()
        payload["ok"] = True
        payload["already_present"] = self.already_present
        payload["restored"] = self.restored
        return payload


class LutInUseError(Exception):
    """Delete refused because Studio clips still reference the asset."""

    def __init__(self, usage: LutUsage) -> None:
        super().__init__("LUT is in use")
        self.usage = usage


def cube_title_from_bytes(data: bytes) -> str:
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError:
        return ""
    for raw in text.splitlines():
        match = TITLE_RE.match(raw.strip())
        if match:
            return match.group(1).strip()
    return ""


def sanitize_display_name(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    text = raw.strip().replace("\\", "/")
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    if text.lower().endswith(".cube"):
        text = text[:-5]
    text = _CONTROL_RE.sub("", text).strip(" .")
    if not text:
        return ""
    return text[:MAX_DISPLAY_NAME_LEN]


def _fallback_imported_name(mtime: float | None = None) -> str:
    if mtime is None:
        stamp = datetime.now().strftime("%Y-%m-%d")
    else:
        stamp = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
    return f"Imported LUT {stamp}"


def default_display_name_for_import(
    *,
    source_label: str,
    data: bytes,
    mtime: float | None = None,
) -> str:
    stem = sanitize_display_name(source_label)
    if stem:
        return stem
    title = sanitize_display_name(cube_title_from_bytes(data))
    if title:
        return title
    return _fallback_imported_name(mtime)


def unique_display_name(db: Database, desired: str, *, exclude_asset: str = "") -> str:
    base = sanitize_display_name(desired) or "Imported LUT"
    taken = {
        name.casefold()
        for name, asset in db.list_lut_display_names()
        if asset != exclude_asset
    }
    if base.casefold() not in taken:
        return base
    index = 2
    while f"{base} ({index})".casefold() in taken:
        index += 1
    return f"{base} ({index})"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(bytes(data)).hexdigest()


def _write_bytes_atomic(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=str(dest.parent),
        prefix=".lut-",
        suffix=".tmp",
        delete=False,
    ) as handle:
        tmp = Path(handle.name)
        handle.write(data)
        handle.flush()
    tmp.replace(dest)


def ensure_legacy_catalog(db: Database, data_dir: Path) -> int:
    """Catalog on-disk ``.cube`` files that have no ``lut_assets`` row yet."""
    root = lut_asset_dir(data_dir)
    added = 0
    known = {row.asset_name for row in db.list_lut_assets()}
    known_sha = {row.content_sha256 for row in db.list_lut_assets()}
    for path in sorted(root.iterdir()):
        if not path.is_file() or not LUT_NAME_RE.fullmatch(path.name):
            continue
        if path.name in known:
            continue
        try:
            data = path.read_bytes()
            validate_cube_bytes(data)
        except (OSError, LutInvalidError):
            continue
        digest = sha256_hex(data)
        if digest in known_sha:
            # Duplicate bytes under another UUID — leave orphan file on disk.
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None
        display = default_display_name_for_import(
            source_label="",
            data=data,
            mtime=mtime,
        )
        display = unique_display_name(db, display)
        imported_at = datetime.now().isoformat(timespec="seconds")
        db.upsert_lut_asset(
            asset_name=path.name,
            display_name=display,
            content_sha256=digest,
            imported_at=imported_at,
        )
        known.add(path.name)
        known_sha.add(digest)
        added += 1
    return added


def scan_lut_usage(db: Database) -> dict[str, LutUsage]:
    """Map asset_name → usage across all Studio projects (persisted clips only)."""
    tallies: dict[str, dict[str, object]] = {}
    for clip_id, project_id, title, effect_settings in db.iter_studio_clips_with_cube_hint():
        look = color_look_from_effect_settings(effect_settings)
        for asset in (look.conversion_lut, look.creative_lut):
            if not asset:
                continue
            bucket = tallies.setdefault(
                asset,
                {"clips": set(), "projects": {}, "titles": {}},
            )
            clips = bucket["clips"]
            projects = bucket["projects"]
            titles = bucket["titles"]
            assert isinstance(clips, set)
            assert isinstance(projects, dict)
            assert isinstance(titles, dict)
            clips.add(clip_id)
            projects[project_id] = True
            label = (title or "").strip() or f"Project {project_id}"
            titles[project_id] = label
    result: dict[str, LutUsage] = {}
    for asset, bucket in tallies.items():
        clips = bucket["clips"]
        projects = bucket["projects"]
        titles = bucket["titles"]
        assert isinstance(clips, set)
        assert isinstance(projects, dict)
        assert isinstance(titles, dict)
        ordered = [titles[pid] for pid in sorted(titles)]
        result[asset] = LutUsage(
            clip_count=len(clips),
            project_count=len(projects),
            project_titles=tuple(ordered[:8]),
        )
    return result


def _file_present(data_dir: Path, asset_name: str) -> bool:
    try:
        require_lut_asset(data_dir, asset_name)
        return True
    except (ValueError, LutMissingError):
        return False


def list_catalog(db: Database, data_dir: Path) -> list[LutCatalogEntry]:
    ensure_legacy_catalog(db, data_dir)
    usage = scan_lut_usage(db)
    entries: list[LutCatalogEntry] = []
    for row in db.list_lut_assets():
        entries.append(
            LutCatalogEntry(
                asset_name=row.asset_name,
                display_name=row.display_name,
                content_sha256=row.content_sha256,
                imported_at=row.imported_at,
                file_present=_file_present(data_dir, row.asset_name),
                usage=usage.get(row.asset_name, LutUsage()),
            )
        )
    entries.sort(key=lambda item: item.display_name.casefold())
    return entries


def import_lut_bytes(
    db: Database,
    data_dir: Path,
    data: bytes,
    *,
    source_label: str = "",
) -> LutImportResult:
    validate_cube_bytes(data)
    ensure_legacy_catalog(db, data_dir)
    digest = sha256_hex(data)
    existing = db.get_lut_asset_by_sha(digest)
    if existing is not None:
        path = resolve_lut_asset(data_dir, existing.asset_name)
        if path.is_file():
            entry = LutCatalogEntry(
                asset_name=existing.asset_name,
                display_name=existing.display_name,
                content_sha256=existing.content_sha256,
                imported_at=existing.imported_at,
                file_present=True,
                usage=scan_lut_usage(db).get(existing.asset_name, LutUsage()),
            )
            return LutImportResult(entry=entry, already_present=True)
        _write_bytes_atomic(path, data)
        entry = LutCatalogEntry(
            asset_name=existing.asset_name,
            display_name=existing.display_name,
            content_sha256=existing.content_sha256,
            imported_at=existing.imported_at,
            file_present=True,
            usage=scan_lut_usage(db).get(existing.asset_name, LutUsage()),
        )
        return LutImportResult(entry=entry, restored=True)

    display = unique_display_name(
        db,
        default_display_name_for_import(source_label=source_label, data=data),
    )
    asset_name = uuid.uuid4().hex + ".cube"
    dest = resolve_lut_asset(data_dir, asset_name)
    _write_bytes_atomic(dest, data)
    imported_at = datetime.now().isoformat(timespec="seconds")
    db.upsert_lut_asset(
        asset_name=asset_name,
        display_name=display,
        content_sha256=digest,
        imported_at=imported_at,
    )
    entry = LutCatalogEntry(
        asset_name=asset_name,
        display_name=display,
        content_sha256=digest,
        imported_at=imported_at,
        file_present=True,
        usage=LutUsage(),
    )
    return LutImportResult(entry=entry)


def import_lut_path(db: Database, data_dir: Path, source: Path) -> LutImportResult:
    path = Path(source)
    if not path.is_file():
        raise LutInvalidError("LUT file was not found")
    if path.suffix.lower() != ".cube":
        raise LutInvalidError("LUT file must use the .cube extension")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise LutInvalidError("LUT file could not be read") from exc
    return import_lut_bytes(db, data_dir, data, source_label=path.name)


def rename_lut(
    db: Database,
    data_dir: Path,
    asset_name: str,
    display_name: str,
) -> LutCatalogEntry:
    if not LUT_NAME_RE.fullmatch(asset_name):
        raise ValueError("LUT reference is invalid")
    row = db.get_lut_asset(asset_name)
    if row is None:
        raise LutMissingError(asset_name)
    cleaned = sanitize_display_name(display_name)
    if not cleaned:
        raise ValueError("Display name is required")
    taken = {
        name.casefold()
        for name, asset in db.list_lut_display_names()
        if asset != asset_name
    }
    if cleaned.casefold() in taken:
        raise ValueError("A LUT with this name already exists")
    db.rename_lut_asset(asset_name, cleaned)
    usage = scan_lut_usage(db).get(asset_name, LutUsage())
    return LutCatalogEntry(
        asset_name=asset_name,
        display_name=cleaned,
        content_sha256=row.content_sha256,
        imported_at=row.imported_at,
        file_present=_file_present(data_dir, asset_name),
        usage=usage,
    )


def delete_lut(db: Database, data_dir: Path, asset_name: str) -> None:
    if not LUT_NAME_RE.fullmatch(asset_name):
        raise ValueError("LUT reference is invalid")
    row = db.get_lut_asset(asset_name)
    if row is None:
        raise LutMissingError(asset_name)
    usage = scan_lut_usage(db).get(asset_name, LutUsage())
    if usage.clip_count > 0:
        raise LutInUseError(usage)
    path = resolve_lut_asset(data_dir, asset_name)
    db.delete_lut_asset(asset_name)
    if path.is_file():
        try:
            path.unlink()
        except OSError as exc:
            raise LutInvalidError("LUT file could not be deleted") from exc


def display_name_map(db: Database, data_dir: Path) -> dict[str, str]:
    """asset_name → display_name for Studio labels."""
    ensure_legacy_catalog(db, data_dir)
    return {row.asset_name: row.display_name for row in db.list_lut_assets()}
