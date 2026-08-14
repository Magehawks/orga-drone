"""Title Card domain: colors, clamp, display lines, wrap, Pillow still (Issue #26)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

from orga_drone.i18n import get_translator, normalize_lang

ITEM_KIND_MEDIA = "media"
ITEM_KIND_TITLE_CARD = "title_card"
TITLE_CARD_KIND = "title_card"

DEFAULT_DURATION_S = 3.0
MIN_DURATION_S = 1.0
MAX_DURATION_S = 10.0
DURATION_STEP_S = 0.1

MAX_TITLE_CHARS = 80
MAX_SUBTITLE_CHARS = 120
MAX_TEXT_LINES = 2
SAFE_MARGIN_FRAC = 0.10

BACKGROUNDS = ("dark", "light", "accent")
DEFAULT_BACKGROUND = "dark"

FALLBACK_MSGID = "Title card"


@dataclass(frozen=True)
class TitleCardColors:
    bg: str
    title: str
    subtitle: str


TITLE_CARD_PRESETS: dict[str, TitleCardColors] = {
    "dark": TitleCardColors(bg="#0a0c0e", title="#f2f4f6", subtitle="#9aabbc"),
    "light": TitleCardColors(bg="#eef1f4", title="#12161c", subtitle="#5a6b7c"),
    "accent": TitleCardColors(bg="#ff9f0a", title="#1a2330", subtitle="#1a2330"),
}


class TitleCardFontError(Exception):
    """No usable system sans font for Title Card export."""


def clamp_card_duration(duration_s: float) -> float:
    raw = float(duration_s)
    stepped = round(raw / DURATION_STEP_S) * DURATION_STEP_S
    clamped = max(MIN_DURATION_S, min(MAX_DURATION_S, stepped))
    return round(clamped, 1)


def normalize_background(value: str | None) -> str:
    key = (value or "").strip().lower()
    if key in TITLE_CARD_PRESETS:
        return key
    raise ValueError("background must be dark, light, or accent")


def normalize_title(text: str | None) -> str:
    return (text or "").strip()[:MAX_TITLE_CHARS]


def normalize_subtitle(text: str | None) -> str:
    return (text or "").strip()[:MAX_SUBTITLE_CHARS]


def fallback_title(locale: str | None) -> str:
    lang = normalize_lang(locale, default="en")
    return get_translator(lang)(FALLBACK_MSGID)


def display_lines(
    title: str | None,
    subtitle: str | None,
    locale: str | None = "en",
) -> tuple[str, str]:
    """Return (primary, secondary) for preview/export. User text is not translated."""
    primary = (title or "").strip()
    secondary = (subtitle or "").strip()
    if not primary and not secondary:
        return fallback_title(locale), ""
    return primary, secondary


def wrap_to_lines(
    text: str,
    *,
    max_width: int,
    max_lines: int,
    measure: Callable[[str], float],
) -> list[str]:
    """Word-wrap ``text`` to ``max_lines``, ellipsizing the last line if needed."""
    clean = (text or "").strip()
    if not clean or max_lines <= 0 or max_width <= 0:
        return []
    words = clean.split()
    lines: list[str] = []
    current = ""
    for index, word in enumerate(words):
        candidate = word if not current else f"{current} {word}"
        if measure(candidate) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = word
        else:
            lines.append(_ellipsis_fit(word, max_width, measure))
            current = ""
        if len(lines) == max_lines:
            rest = " ".join(words[index + 1 :])
            overflow = " ".join(part for part in (current, rest) if part).strip()
            if overflow:
                lines[-1] = _ellipsis_fit(overflow, max_width, measure)
            current = ""
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    elif current and lines:
        lines[-1] = _ellipsis_fit(f"{lines[-1]} {current}".strip(), max_width, measure)
    return lines[:max_lines]


def _ellipsis_fit(text: str, max_width: int, measure: Callable[[str], float]) -> str:
    if measure(text) <= max_width:
        return text
    ellipsis = "…"
    if measure(ellipsis) > max_width:
        return ""
    lo, hi = 0, len(text)
    best = ellipsis
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = text[:mid].rstrip() + ellipsis
        if measure(candidate) <= max_width:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def resolve_title_card_font() -> Path:
    """System sans used for export. Override with ``ORGA_DRONE_TITLE_FONT``."""
    override = os.getenv("ORGA_DRONE_TITLE_FONT", "").strip()
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return path
    candidates = (
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\calibri.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/freefont/FreeSans.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/System/Library/Fonts/Helvetica.ttc"),
        Path("/Library/Fonts/Arial.ttf"),
    )
    for path in candidates:
        if path.is_file():
            return path
    raise TitleCardFontError("No system sans font found for Title Card export.")


def render_title_card_image(
    *,
    width: int,
    height: int,
    title: str,
    subtitle: str,
    background: str,
    locale: str | None = "en",
) -> "PILImage":
    """Pillow RGB still at export size. Caller writes JPEG; never persists as SoT."""
    from PIL import Image, ImageDraw, ImageFont

    bg_key = normalize_background(background)
    colors = TITLE_CARD_PRESETS[bg_key]
    img = Image.new("RGB", (int(width), int(height)), colors.bg)
    draw = ImageDraw.Draw(img)
    margin = max(8, int(min(width, height) * SAFE_MARGIN_FRAC))
    max_w = max(32, int(width) - 2 * margin)
    primary, secondary = display_lines(title, subtitle, locale)
    font_path = resolve_title_card_font()
    title_size = max(18, int(height * 0.08))
    sub_size = max(14, int(height * 0.045))
    title_font = ImageFont.truetype(str(font_path), title_size)
    sub_font = ImageFont.truetype(str(font_path), sub_size)

    def _measure(font: ImageFont.FreeTypeFont) -> Callable[[str], float]:
        def _inner(text: str) -> float:
            box = font.getbbox(text)
            return float(box[2] - box[0])

        return _inner

    title_lines = wrap_to_lines(
        primary, max_width=max_w, max_lines=MAX_TEXT_LINES, measure=_measure(title_font)
    )
    sub_lines = wrap_to_lines(
        secondary, max_width=max_w, max_lines=MAX_TEXT_LINES, measure=_measure(sub_font)
    )
    line_gap = max(4, int(height * 0.012))
    block_gap = max(8, int(height * 0.03)) if title_lines and sub_lines else 0

    def _line_h(font: ImageFont.FreeTypeFont, text: str) -> int:
        box = font.getbbox(text or "Ag")
        return int(box[3] - box[1])

    title_h = sum(_line_h(title_font, line) for line in title_lines)
    if title_lines:
        title_h += line_gap * (len(title_lines) - 1)
    sub_h = sum(_line_h(sub_font, line) for line in sub_lines)
    if sub_lines:
        sub_h += line_gap * (len(sub_lines) - 1)
    total_h = title_h + block_gap + sub_h
    y = max(margin, (int(height) - total_h) // 2)

    def _draw_centered(
        lines: list[str], font: ImageFont.FreeTypeFont, fill: str, start_y: int
    ) -> int:
        cy = start_y
        for i, line in enumerate(lines):
            box = font.getbbox(line)
            tw = box[2] - box[0]
            x = max(margin, (int(width) - tw) // 2)
            draw.text((x, cy), line, font=font, fill=fill)
            cy += _line_h(font, line)
            if i < len(lines) - 1:
                cy += line_gap
        return cy

    y = _draw_centered(title_lines, title_font, colors.title, y)
    if sub_lines:
        y += block_gap
        _draw_centered(sub_lines, sub_font, colors.subtitle, y)
    return img
