"""i18n helpers – JSON catalogs under locales/<lang>/LC_MESSAGES/."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Callable

SUPPORTED_LANGS = ("de", "en")
LOCALES_DIR = Path(__file__).resolve().parent / "locales"


@lru_cache(maxsize=8)
def _catalog(lang: str) -> dict[str, str]:
    code = lang if lang in SUPPORTED_LANGS else "en"
    path = LOCALES_DIR / code / "LC_MESSAGES" / "messages.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()}
    except (OSError, json.JSONDecodeError):
        return {}


def clear_catalog_cache() -> None:
    _catalog.cache_clear()


def get_translator(lang: str) -> Callable[[str], str]:
    catalog = _catalog(lang)

    def _(message: str) -> str:
        return catalog.get(message, message)

    return _


def normalize_lang(lang: str | None, default: str = "de") -> str:
    if not lang:
        return default if default in SUPPORTED_LANGS else "en"
    code = lang.lower().split("-")[0]
    return code if code in SUPPORTED_LANGS else default
