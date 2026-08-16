"""UI fonts are local application assets, not a Google Fonts CDN request."""

from __future__ import annotations

from orga_drone.app import PACKAGE_DIR, STATIC_DIR

_REQUIRED_FONTS = (
    "outfit-latin-400.woff2",
    "outfit-latin-500.woff2",
    "outfit-latin-600.woff2",
    "outfit-latin-700.woff2",
    "sora-latin-600.woff2",
    "sora-latin-700.woff2",
    "ibm-plex-mono-latin-400.woff2",
    "ibm-plex-mono-latin-500.woff2",
)


def test_base_template_does_not_request_google_fonts() -> None:
    html = (PACKAGE_DIR / "templates" / "base.html").read_text(encoding="utf-8")
    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html


def test_app_css_declares_local_font_faces() -> None:
    css = (STATIC_DIR / "css" / "app.css").read_text(encoding="utf-8")
    assert '@font-face' in css
    assert 'url("/static/fonts/outfit-latin-400.woff2")' in css
    assert 'url("/static/fonts/sora-latin-600.woff2")' in css
    assert 'url("/static/fonts/ibm-plex-mono-latin-400.woff2")' in css


def test_ui_font_files_exist() -> None:
    fonts = STATIC_DIR / "fonts"
    for name in _REQUIRED_FONTS:
        path = fonts / name
        assert path.is_file(), path
        assert path.stat().st_size > 1000
