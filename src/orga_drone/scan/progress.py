"""Scan progress events and safe path display for UI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class ScanProgress:
    """Snapshot emitted during a library scan.

    ``current_path`` must be UI-safe (filename or path relative to the
    library root) — never an absolute filesystem path.
    """

    phase: str  # discovering | indexing | grouping | done
    discovered: int = 0
    processed: int = 0
    current_path: str | None = None
    root_id: int | None = None


ProgressCallback = Callable[[ScanProgress], None]


def display_scan_path(path: Path, root_path: Path) -> str:
    """Return a UI-safe path: relative to root, else basename only."""
    try:
        root = root_path.resolve()
        resolved = path.resolve()
        rel = resolved.relative_to(root)
        text = str(rel).replace("\\", "/")
        return text if text and text != "." else path.name
    except (ValueError, OSError):
        return path.name
