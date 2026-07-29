"""Natural-language and structured media search helpers."""

from __future__ import annotations

import calendar
import re
from dataclasses import asdict, dataclass, field
from typing import Any

_MONTHS: dict[str, int] = {
    "jan": 1,
    "january": 1,
    "januar": 1,
    "feb": 2,
    "february": 2,
    "februar": 2,
    "mar": 3,
    "march": 3,
    "märz": 3,
    "maerz": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "mai": 5,
    "jun": 6,
    "june": 6,
    "juni": 6,
    "jul": 7,
    "july": 7,
    "juli": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "okt": 10,
    "oktober": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
    "dez": 12,
    "dezember": 12,
}

_KIND_VIDEO = frozenset(
    {"video", "videos", "clip", "clips", "vid", "vids", "film", "filme"}
)
_KIND_PHOTO = frozenset(
    {
        "photo",
        "photos",
        "picture",
        "pictures",
        "pic",
        "pics",
        "image",
        "images",
        "bild",
        "bilder",
        "foto",
        "fotos",
    }
)
_FAVORITE = frozenset(
    {"favorite", "favorites", "favourite", "favourites", "favorit", "favoriten"}
)
_STOPWORDS = frozenset(
    {
        "a",
        "all",
        "alle",
        "an",
        "aus",
        "das",
        "de",
        "dem",
        "den",
        "der",
        "des",
        "die",
        "from",
        "für",
        "in",
        "im",
        "mein",
        "meine",
        "meiner",
        "meinen",
        "meines",
        "mir",
        "my",
        "of",
        "show",
        "the",
        "und",
        "and",
        "vom",
        "von",
        "zeig",
        "zeige",
        "zeigen",
        "bitte",
        "mit",
        "nur",
        "only",
        "urlaub",
        "vacation",
        "holiday",
        "holidays",
        "trip",
        "reise",
    }
)

_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
_ISO_MONTH_RE = re.compile(r"^(19|20)\d{2}[-/](0?[1-9]|1[0-2])$")
_ISO_DAY_RE = re.compile(r"^(19|20)\d{2}[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])$")
_MONTH_YEAR_RE = re.compile(
    r"^(?P<month>[a-zäöü.]+)\s+(?P<year>(?:19|20)\d{2})$",
    re.IGNORECASE,
)
_YEAR_MONTH_RE = re.compile(
    r"^(?P<year>(?:19|20)\d{2})\s+(?P<month>[a-zäöü.]+)$",
    re.IGNORECASE,
)


@dataclass
class MediaSearch:
    """Structured filters for media library queries."""

    kind: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    q: str | None = None
    place: str | None = None
    tags: list[str] = field(default_factory=list)
    favorite: bool | None = None
    limit: int | None = None

    def effective_q(self) -> str | None:
        parts: list[str] = []
        if self.q:
            parts.extend(self.q.split())
        if self.place:
            parts.extend(self.place.split())
        for tag in self.tags:
            if tag and tag not in parts:
                parts.append(tag)
        return " ".join(parts) if parts else None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["effective_q"] = self.effective_q()
        return data

    def summary_parts(self) -> list[str]:
        parts: list[str] = []
        if self.kind == "video":
            parts.append("video")
        elif self.kind == "photo":
            parts.append("photo")
        if self.date_from and self.date_to:
            if self.date_from[:7] == self.date_to[:7] and self.date_from.endswith("-01"):
                parts.append(self.date_from[:7])
            elif self.date_from == self.date_to:
                parts.append(self.date_from)
            else:
                parts.append(f"{self.date_from}…{self.date_to}")
        elif self.date_from:
            parts.append(f"≥{self.date_from}")
        elif self.date_to:
            parts.append(f"≤{self.date_to}")
        if self.place:
            parts.append(self.place)
        if self.tags:
            parts.append(", ".join(self.tags))
        if self.q:
            parts.append(self.q)
        if self.favorite is True:
            parts.append("favorite")
        return parts


def _normalize_month_token(token: str) -> str:
    return token.strip(".").lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")


def _month_number(token: str) -> int | None:
    key = token.strip(".").lower()
    if key in _MONTHS:
        return _MONTHS[key]
    return _MONTHS.get(_normalize_month_token(token))


def month_bounds(year: int, month: int) -> tuple[str, str]:
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}"


def year_bounds(year: int) -> tuple[str, str]:
    return f"{year:04d}-01-01", f"{year:04d}-12-31"


def normalize_iso_date(value: str | None) -> str | None:
    """Normalize YYYY-MM-DD / YYYY-MM / YYYY-M-D into YYYY-MM-DD (start of month if needed)."""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    m = _ISO_DAY_RE.match(text)
    if m:
        y, mo, d = (int(p) for p in re.split(r"[-/]", text))
        return f"{y:04d}-{mo:02d}-{d:02d}"
    m = _ISO_MONTH_RE.match(text)
    if m:
        y, mo = (int(p) for p in re.split(r"[-/]", text))
        return f"{y:04d}-{mo:02d}-01"
    if _YEAR_RE.match(text):
        return f"{int(text):04d}-01-01"
    return None


def normalize_iso_date_end(value: str | None) -> str | None:
    """Like normalize_iso_date, but YYYY-MM / YYYY expand to the last day."""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if _ISO_DAY_RE.match(text):
        return normalize_iso_date(text)
    if _ISO_MONTH_RE.match(text):
        y, mo = (int(p) for p in re.split(r"[-/]", text))
        return month_bounds(y, mo)[1]
    if _YEAR_RE.match(text):
        return year_bounds(int(text))[1]
    return normalize_iso_date(text)


def parse_natural_query(text: str) -> MediaSearch:
    """Rule-based NL → MediaSearch (DE/EN) for common library questions."""
    raw = (text or "").strip()
    if not raw:
        return MediaSearch()

    lowered = raw.lower()
    # Pull out ISO-like dates first so tokenization stays simple.
    date_from: str | None = None
    date_to: str | None = None
    work = lowered

    for match in list(_ISO_DAY_RE.finditer(work)):
        day = normalize_iso_date(match.group(0))
        if day:
            date_from = day
            date_to = day
        work = work[: match.start()] + " " + work[match.end() :]

    for match in list(_ISO_MONTH_RE.finditer(work)):
        y, mo = (int(p) for p in re.split(r"[-/]", match.group(0)))
        date_from, date_to = month_bounds(y, mo)
        work = work[: match.start()] + " " + work[match.end() :]

    tokens = re.findall(r"[0-9a-zäöü.]+", work, flags=re.IGNORECASE)
    kind: str | None = None
    favorite: bool | None = None
    place_parts: list[str] = []
    tag_parts: list[str] = []
    q_parts: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""

        pair = f"{tok} {nxt}"
        my = _MONTH_YEAR_RE.match(pair)
        ym = _YEAR_MONTH_RE.match(pair)
        if my:
            month = _month_number(my.group("month"))
            if month:
                date_from, date_to = month_bounds(int(my.group("year")), month)
                i += 2
                continue
        if ym:
            month = _month_number(ym.group("month"))
            if month:
                date_from, date_to = month_bounds(int(ym.group("year")), month)
                i += 2
                continue

        month = _month_number(tok)
        if month and _YEAR_RE.match(nxt):
            date_from, date_to = month_bounds(int(nxt), month)
            i += 2
            continue
        if _YEAR_RE.match(tok) and _month_number(nxt):
            date_from, date_to = month_bounds(int(tok), _month_number(nxt) or 1)
            i += 2
            continue
        if _YEAR_RE.match(tok) and date_from is None:
            date_from, date_to = year_bounds(int(tok))
            i += 1
            continue

        low = tok.lower()
        if low in _KIND_VIDEO:
            kind = "video"
            i += 1
            continue
        if low in _KIND_PHOTO:
            kind = "photo"
            i += 1
            continue
        if low in _FAVORITE:
            favorite = True
            i += 1
            continue
        if low in {"urlaub", "vacation", "holiday", "holidays", "trip", "reise"}:
            # Keep the original token for tag/note match; also add DE synonym.
            tag_parts.append(low)
            if low not in {"urlaub", "reise"}:
                tag_parts.append("urlaub")
            i += 1
            continue
        if low in _STOPWORDS or low in {".", ""}:
            i += 1
            continue

        # Remaining content words → place + free-text (same token helps tag/path match).
        place_parts.append(tok)
        q_parts.append(tok)
        i += 1

    place = " ".join(place_parts) if place_parts else None
    q = " ".join(q_parts) if q_parts else None
    # Deduplicate vacation-style tags while keeping order.
    tags: list[str] = []
    for t in tag_parts:
        if t not in tags:
            tags.append(t)

    return MediaSearch(
        kind=kind,
        date_from=date_from,
        date_to=date_to,
        q=q,
        place=place,
        tags=tags,
        favorite=favorite,
    )


def merge_search(
    base: MediaSearch,
    *,
    kind: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    place: str | None = None,
    tags: list[str] | None = None,
    favorite: bool | None = None,
    limit: int | None = None,
) -> MediaSearch:
    """Explicit filters win over parsed NL fields when both are set."""
    return MediaSearch(
        kind=kind or base.kind,
        date_from=normalize_iso_date(date_from) or base.date_from,
        date_to=normalize_iso_date_end(date_to) or base.date_to,
        q=q if q not in (None, "") else base.q,
        place=place if place not in (None, "") else base.place,
        tags=tags if tags is not None else list(base.tags),
        favorite=favorite if favorite is not None else base.favorite,
        limit=limit if limit is not None else base.limit,
    )


def media_search_from_payload(payload: dict[str, Any]) -> MediaSearch:
    ask = str(payload.get("ask") or payload.get("query") or "").strip()
    parsed = parse_natural_query(ask) if ask else MediaSearch()
    tags_raw = payload.get("tags")
    tags: list[str] | None
    if tags_raw is None:
        tags = None
    elif isinstance(tags_raw, str):
        tags = [t.strip() for t in re.split(r"[,;]", tags_raw) if t.strip()]
    else:
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]

    fav = payload.get("favorite")
    favorite: bool | None
    if fav is None or fav == "":
        favorite = None
    elif isinstance(fav, bool):
        favorite = fav
    else:
        favorite = str(fav).lower() in {"1", "true", "yes", "on"}

    limit_raw = payload.get("limit")
    limit = int(limit_raw) if limit_raw not in (None, "") else None

    return merge_search(
        parsed,
        kind=(str(payload["kind"]).strip() or None) if payload.get("kind") else None,
        date_from=str(payload["date_from"]) if payload.get("date_from") else None,
        date_to=str(payload["date_to"]) if payload.get("date_to") else None,
        q=str(payload["q"]).strip() if payload.get("q") not in (None, "") else None,
        place=str(payload["place"]).strip() if payload.get("place") not in (None, "") else None,
        tags=tags,
        favorite=favorite,
        limit=limit,
    )
