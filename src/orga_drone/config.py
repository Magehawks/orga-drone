"""Local configuration – no secrets required for the MVP."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def is_packaged() -> bool:
    """True when running as a PyInstaller (or similar) frozen binary."""
    if getattr(sys, "frozen", False):
        return True
    flag = os.getenv("ORGA_DRONE_PACKAGED", "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def _is_absolute_data_path(value: str) -> bool:
    """Return True for absolute POSIX or Windows path strings.

    Used for ``XDG_DATA_HOME`` validation so relative values are rejected
    even when tests inject a foreign ``os.name`` into pathlib.
    """
    if not value:
        return False
    if value.startswith(("/", "\\")):
        return True
    # Windows drive paths: ``C:\data`` or ``C:/data``
    if len(value) >= 3 and value[0].isalpha() and value[1] == ":" and value[2] in "/\\":
        return True
    return False


def _xdg_data_home() -> Path:
    """Resolve XDG data home for Linux and other non-Windows, non-macOS hosts.

    Per the XDG Base Directory Spec, ``XDG_DATA_HOME`` must be absolute.
    Relative or empty values are ignored and ``~/.local/share`` is used.
    """
    raw = os.environ.get("XDG_DATA_HOME", "").strip()
    if raw:
        expanded = str(Path(raw).expanduser())
        if _is_absolute_data_path(expanded):
            return Path(expanded)
    return Path.home() / ".local" / "share"


def _default_data_dir(
    *,
    os_name: str | None = None,
    platform: str | None = None,
) -> Path:
    """Resolve the default app data directory for the current (or injected) OS.

    ``os_name`` / ``platform`` are for tests only; production callers omit them.
    """
    override = os.getenv("ORGA_DRONE_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    name = os.name if os_name is None else os_name
    plat = sys.platform if platform is None else platform

    if name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif plat == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = _xdg_data_home()

    return (base / "orga-drone").resolve()


def _geocode_mode() -> str:
    raw = os.getenv("ORGA_DRONE_GEOCODE", "offline").strip().lower()
    return raw if raw in {"off", "offline"} else "offline"


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("ORGA_DRONE_HOST", "127.0.0.1")
    port: int = int(os.getenv("ORGA_DRONE_PORT", "8765"))
    default_lang: str = os.getenv("ORGA_DRONE_LANG", "de")
    geocode_mode: str = _geocode_mode()
    data_dir: Path = _default_data_dir()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "orga-drone.sqlite3"

    @property
    def theme_path(self) -> Path:
        return self.data_dir / "theme.json"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "thumbs").mkdir(parents=True, exist_ok=True)


settings = Settings()
