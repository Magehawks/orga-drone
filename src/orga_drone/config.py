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


def _default_data_dir() -> Path:
    override = os.getenv("ORGA_DRONE_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif (Path.home() / "Library" / "Application Support").exists():
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    return (base / "orga-drone").resolve()


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("ORGA_DRONE_HOST", "127.0.0.1")
    port: int = int(os.getenv("ORGA_DRONE_PORT", "8765"))
    default_lang: str = os.getenv("ORGA_DRONE_LANG", "de")
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
