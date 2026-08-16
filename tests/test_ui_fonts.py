"""UI fonts and local app icon assets."""

from __future__ import annotations

from pathlib import Path

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


def test_base_template_uses_local_favicon() -> None:
    html = (PACKAGE_DIR / "templates" / "base.html").read_text(encoding="utf-8")
    assert 'href="/static/icons/orga-drone.png"' in html
    assert 'href="/static/icons/orga-drone.ico"' in html
    assert "fonts.googleapis.com" not in html


def test_app_icon_png_exists() -> None:
    png = STATIC_DIR / "icons" / "orga-drone.png"
    assert png.is_file()
    assert png.stat().st_size > 1000


def test_packaging_ico_has_standard_sizes() -> None:
    from PIL import Image

    repo = Path(__file__).resolve().parents[1]
    ico = repo / "packaging" / "assets" / "orga-drone.ico"
    static_ico = STATIC_DIR / "icons" / "orga-drone.ico"
    assert ico.is_file()
    assert static_ico.is_file()
    assert ico.read_bytes() == static_ico.read_bytes()
    with Image.open(ico) as image:
        assert image.format == "ICO"
        sizes = sorted(image.ico.sizes())
    assert sizes == [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
