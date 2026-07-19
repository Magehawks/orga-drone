"""Theme preference helpers – cookie + optional app-data JSON."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

THEME_MODES = ("dark", "light", "custom")
DEFAULT_THEME = "dark"
_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

DEFAULT_CUSTOM = {
    "accent": "#3db8a0",
    "background": "#f4f7f9",
    "panel": "#ffffff",
}


@dataclass(frozen=True)
class ThemePrefs:
    mode: str = DEFAULT_THEME
    accent: str = DEFAULT_CUSTOM["accent"]
    background: str = DEFAULT_CUSTOM["background"]
    panel: str = DEFAULT_CUSTOM["panel"]

    def normalize(self) -> ThemePrefs:
        mode = self.mode if self.mode in THEME_MODES else DEFAULT_THEME
        return ThemePrefs(
            mode=mode,
            accent=normalize_hex(self.accent, DEFAULT_CUSTOM["accent"]),
            background=normalize_hex(self.background, DEFAULT_CUSTOM["background"]),
            panel=normalize_hex(self.panel, DEFAULT_CUSTOM["panel"]),
        )


def normalize_theme(mode: str | None, default: str = DEFAULT_THEME) -> str:
    if not mode:
        return default if default in THEME_MODES else DEFAULT_THEME
    code = mode.lower().strip()
    return code if code in THEME_MODES else (default if default in THEME_MODES else DEFAULT_THEME)


def normalize_hex(value: str | None, fallback: str) -> str:
    raw = (value or "").strip()
    if not _HEX.match(raw):
        return fallback
    if len(raw) == 4:
        return "#" + "".join(ch * 2 for ch in raw[1:]).lower()
    return raw.lower()


def _channel(hex6: str, index: int) -> float:
    return int(hex6[index : index + 2], 16) / 255.0


def relative_luminance(hex_color: str) -> float:
    h = normalize_hex(hex_color, "#000000").lstrip("#")

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = lin(_channel(h, 0)), lin(_channel(h, 2)), lin(_channel(h, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_text(bg_hex: str) -> str:
    return "#1a2330" if relative_luminance(bg_hex) > 0.45 else "#e8eef4"


def contrast_muted(bg_hex: str) -> str:
    return "#5a6b7c" if relative_luminance(bg_hex) > 0.45 else "#9aabbc"


def load_theme_file(path: Path) -> ThemePrefs | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return ThemePrefs(
        mode=str(data.get("mode") or DEFAULT_THEME),
        accent=str(data.get("accent") or DEFAULT_CUSTOM["accent"]),
        background=str(data.get("background") or DEFAULT_CUSTOM["background"]),
        panel=str(data.get("panel") or DEFAULT_CUSTOM["panel"]),
    ).normalize()


def save_theme_file(path: Path, prefs: ThemePrefs) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = asdict(prefs.normalize())
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def prefs_from_cookies(cookies: dict[str, str], file_prefs: ThemePrefs | None = None) -> ThemePrefs:
    base = file_prefs or ThemePrefs()
    mode = normalize_theme(cookies.get("theme"), base.mode)
    return ThemePrefs(
        mode=mode,
        accent=normalize_hex(cookies.get("theme_accent"), base.accent),
        background=normalize_hex(cookies.get("theme_bg"), base.background),
        panel=normalize_hex(cookies.get("theme_panel"), base.panel),
    ).normalize()


def custom_css_vars(prefs: ThemePrefs) -> str:
    p = prefs.normalize()
    text = contrast_text(p.background)
    muted = contrast_muted(p.background)
    deep_is_light = relative_luminance(p.background) > 0.45
    surface_deep = (
        f"color-mix(in srgb, {p.background} 70%, #c5d0db)"
        if deep_is_light
        else f"color-mix(in srgb, {p.background} 70%, #000)"
    )
    border = (
        f"color-mix(in srgb, {text} 16%, {p.background})"
        if deep_is_light
        else f"color-mix(in srgb, {text} 22%, {p.background})"
    )
    return (
        f"--bg: {p.background}; "
        f"--panel: {p.panel}; "
        f"--accent: {p.accent}; "
        f"--accent-dim: color-mix(in srgb, {p.accent} 78%, #000); "
        f"--text: {text}; "
        f"--muted: {muted}; "
        f"--border: {border}; "
        f"--input-bg: {p.panel}; "
        f"--surface-deep: {surface_deep}; "
        f"--top-bg: color-mix(in srgb, {p.panel} 88%, transparent); "
        f"--bg-glow-1: color-mix(in srgb, {p.accent} 22%, {p.background}); "
        f"--bg-glow-2: color-mix(in srgb, {p.accent} 12%, {p.background}); "
        f"--kind-bg: {surface_deep}; "
        f"--on-accent: {contrast_text(p.accent)};"
    )
