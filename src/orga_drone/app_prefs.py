"""Local app preferences (non-settings-page) stored under the data directory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orga_drone.config import settings

_PREFS_NAME = "app_prefs.json"


def prefs_path() -> Path:
    settings.ensure_dirs()
    return settings.data_dir / _PREFS_NAME


def load_prefs() -> dict[str, Any]:
    path = prefs_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_prefs(data: dict[str, Any]) -> None:
    path = prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def get_last_export_directory() -> str | None:
    raw = load_prefs().get("last_export_directory")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def set_last_export_directory(directory: str | Path) -> None:
    data = load_prefs()
    data["last_export_directory"] = str(Path(directory))
    save_prefs(data)
