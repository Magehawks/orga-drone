"""FastAPI application – local web UI for orga-drone."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Callable, NoReturn
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from orga_drone import __version__
from orga_drone.app_prefs import get_check_updates, set_check_updates
from orga_drone.config import settings
from orga_drone.home_hero import cached_thumbnail, pick_home_media_id
from orga_drone.local_cache import (
    cache_sizes,
    clear_regenerable_cache,
    format_bytes as format_cache_bytes,
)
from orga_drone.local_http import LoopbackOriginMiddleware
from orga_drone.updates import OFFICIAL_DOWNLOAD_URL, UpdateChecker, installed_version
from orga_drone.browse_timeline import (
    build_timeline_nav,
    group_timeline_page,
    parse_timeline_focus,
)
from orga_drone.db import Database, make_identity_key, parse_tags, track_from_json
from orga_drone.dupes import (
    DURATION_TOLERANCE_S,
    RECORDED_AT_TOLERANCE_S,
    find_duplicate_groups,
    media_row_to_fingerprint,
)
from orga_drone.studio_audio import detached_audio_from_effect_settings
from orga_drone.studio_cut import section_repeats_from_effect_settings
from orga_drone.studio_forward_loop import (
    clip_forward_loop_view,
    effective_item_seconds,
    resolve_forward_loop,
    soundtrack_once_s,
)
from orga_drone.studio_effect_lane import stored_lane
from orga_drone.studio_estimate import (
    DEFAULT_PHOTO_DURATION_S,
    effective_seconds,
    summarize_studio_items,
)
from orga_drone.studio_history import (
    clear_studio_history,
    history_flags,
    redo_story,
    story_edit,
    undo_story,
)
from orga_drone.studio_frame import (
    frame_from_effect_settings,
    frame_preview_model,
)
from orga_drone.studio_hud import empty_hud_state, hud_client_state
from orga_drone.studio_image import (
    color_profile_hint_from_srt,
    export_payload_sets_adjust,
    image_adjust_from_effect_settings,
    image_adjust_from_export_payload,
    image_adjust_preview_model,
    saturation_ramp_from_effect_settings,
)
from orga_drone.studio_detail import (
    detail_from_effect_settings,
    detail_preview_model,
)
from orga_drone.studio_looks import (
    look_id_from_effect_settings,
    quick_looks_preview_model,
)
from orga_drone.lut_library import (
    LutInUseError,
    delete_lut,
    import_lut_bytes,
    import_lut_path,
    list_catalog,
    rename_lut,
)
from orga_drone.studio_lut import (
    LutInvalidError,
    LutMissingError,
    color_look_from_effect_settings,
    color_look_preview_model,
    lut_asset_dir,
    require_lut_asset,
)
from orga_drone.studio_color_animation import (
    color_animation_from_effect_settings,
    color_animation_preview_model,
)
from orga_drone.studio_preview_frame import (
    PreviewFrameError,
    PreviewFrameRequest,
    look_needs_preview_still,
    quantize_preview_time,
    render_preview_frame,
)
from orga_drone.studio_map import (
    cached_osm_tile,
    gps_from_stored,
    map_from_effect_settings,
    map_preview_model,
    route_preview,
)
from orga_drone.studio_mask import mask_preview_model, masks_from_effect_settings
from orga_drone.studio_merge import MERGE_REASONS, MergeBlocked
from orga_drone.studio_reuse import REUSE_REASONS, ReuseBlocked
from orga_drone.studio_overlay import (
    overlay_preview_model,
    overlays_from_effect_settings,
    resolve_overlay_asset,
    store_overlay_asset,
)
from orga_drone.studio_title_card import TITLE_CARD_KIND, display_lines
from orga_drone.studio_transition import (
    apply_for_items,
    clip_flex_s,
    item_effective_seconds,
    normalize_type,
)
from orga_drone.export import build_spot_geojson, spot_download_filename
from orga_drone.ffmpeg_bin import ffmpeg_available
from orga_drone.flight_view import (
    build_flight_playlist,
    concat_clip_tracks,
    flight_map_center,
    normalize_detail_tab,
)
from orga_drone.i18n import SUPPORTED_LANGS, get_translator, normalize_lang
from orga_drone.media_files import resolve_media_file, resolve_proxy_file
from orga_drone.ops.merge import MergeError, default_merge_name, merge_flow
from orga_drone.ops.rename import RenameError, rename_media
from orga_drone.scan import offline_root_ids, scan_all_roots, scan_root
from orga_drone.scan.jobs import ScanJobStore
from orga_drone.scan.progress import ProgressCallback
from orga_drone.export.jobs import ExportJobStore
from orga_drone.search import (
    MediaSearch,
    media_search_from_payload,
    merge_search,
    parse_natural_query,
)
from orga_drone.theme import (
    ThemePrefs,
    custom_css_vars,
    load_theme_file,
    normalize_hex,
    normalize_theme,
    prefs_from_cookies,
    save_theme_file,
)
from orga_drone.thumbs import browser_can_display_photo, ensure_photo_preview, ensure_thumbnail

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

MIME_BY_SUFFIX = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".m4v": "video/x-m4v",
    ".mkv": "video/x-matroska",
    ".lrf": "video/mp4",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".dng": "image/x-adobe-dng",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
}


def format_bytes(num: int | None) -> str:
    if num is None:
        return "—"
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{num} B"


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def osm_link(lat: float, lon: float) -> str:
    return f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=16/{lat}/{lon}"


def format_place(place: dict[str, Any] | None) -> str:
    if not place:
        return ""
    parts: list[str] = []
    seen: set[str] = set()
    city = (place.get("city") or "").strip()
    district = (place.get("district") or "").strip()
    region = (place.get("region") or "").strip()
    country = (place.get("country") or "").strip()

    def add(label: str) -> None:
        if not label:
            return
        key = label.casefold()
        if key in seen:
            return
        seen.add(key)
        parts.append(label)

    add(city)
    if district and district.casefold() != city.casefold():
        add(district)
    add(region)
    add(country)
    return ", ".join(parts)


# Cap DOM size in Browse (WebView2 keeps decoded thumbs for every card).
BROWSE_PAGE_SIZE = 50
BROWSE_PAGE_SIZES = (50, 100, 200)


def browse_resolve_page_size(raw: Any) -> int:
    """Allowlist Browse page length; unknown values fall back to the default."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return BROWSE_PAGE_SIZE
    if value in BROWSE_PAGE_SIZES:
        return value
    return BROWSE_PAGE_SIZE


def browse_page_clamp(page: int, *, total: int, page_size: int = BROWSE_PAGE_SIZE) -> int:
    """Normalize a 1-based page index into a valid range for ``total`` rows."""
    size = max(1, int(page_size))
    total_pages = max(1, (max(0, int(total)) + size - 1) // size)
    try:
        raw = int(page)
    except (TypeError, ValueError):
        raw = 1
    return max(1, min(raw, total_pages))


def browse_pagination(
    *,
    total: int,
    page: int,
    page_size: int = BROWSE_PAGE_SIZE,
) -> dict[str, Any]:
    """Build pagination metadata for the Browse template."""
    size = max(1, int(page_size))
    total_n = max(0, int(total))
    total_pages = max(1, (total_n + size - 1) // size) if total_n else 1
    page_n = browse_page_clamp(page, total=total_n, page_size=size)
    offset = (page_n - 1) * size
    showing_to = min(offset + size, total_n) if total_n else 0
    return {
        "page": page_n,
        "page_size": size,
        "total": total_n,
        "total_pages": total_pages,
        "offset": offset,
        "has_prev": page_n > 1,
        "has_next": page_n < total_pages and total_n > 0,
        "prev_page": page_n - 1,
        "next_page": page_n + 1,
        "showing_from": (offset + 1) if total_n else 0,
        "showing_to": showing_to,
    }


def browse_filter_query(filters: dict[str, Any], *, page: int | None = None) -> str:
    """URL query string for Browse links (filters + optional page)."""
    params: dict[str, str] = {}
    for key, value in filters.items():
        if value is None or value == "":
            continue
        params[str(key)] = str(value)
    if page is not None and page > 1:
        params["page"] = str(page)
    return urlencode(params)


def create_app() -> FastAPI:
    settings.ensure_dirs()
    clear_studio_history()
    db = Database(settings.db_path)

    app = FastAPI(title="orga-drone", version=__version__)
    app.add_middleware(LoopbackOriginMiddleware)
    app.state.db = db

    @app.middleware("http")
    async def attach_story_history_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        path = request.url.path
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return response
        if not (path.startswith("/api/studio") or path.startswith("/studio/")):
            return response
        project = db.resolve_studio_page_project()
        flags = history_flags(project.id if project is not None else None)
        response.headers["X-Studio-Can-Undo"] = "1" if flags["can_undo"] else "0"
        response.headers["X-Studio-Can-Redo"] = "1" if flags["can_redo"] else "0"
        return response

    def _history_group(request: Request) -> str | None:
        raw = request.headers.get("x-studio-history-group", "").strip()
        if not raw:
            return None
        return raw[:64]

    def _clip_project_id(studio_item_id: int) -> int | None:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT project_id FROM studio_clips WHERE id = ?",
                (studio_item_id,),
            ).fetchone()
        if row is None:
            return None
        return int(row["project_id"])

    app.state.scan_jobs = ScanJobStore()
    app.state.export_jobs = ExportJobStore()
    app.state.update_checker = UpdateChecker()

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["filesize"] = format_bytes
    templates.env.filters["duration"] = format_duration
    templates.env.filters["place_label"] = format_place

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def lang_from_request(request: Request) -> str:
        cookie = request.cookies.get("lang")
        return normalize_lang(cookie, settings.default_lang)

    def view_from_request(request: Request, override: str | None = None) -> str:
        raw = (override or request.cookies.get("view") or "grid").lower()
        return raw if raw in {"grid", "list", "timeline"} else "grid"

    def theme_from_request(request: Request) -> ThemePrefs:
        stored = load_theme_file(settings.theme_path)
        return prefs_from_cookies(dict(request.cookies), stored)

    def theme_cookie_age() -> int:
        return 365 * 24 * 3600

    def apply_theme_cookies(response: Response, prefs: ThemePrefs) -> None:
        p = prefs.normalize()
        age = theme_cookie_age()
        response.set_cookie("theme", p.mode, max_age=age)
        response.set_cookie("theme_accent", p.accent, max_age=age)
        response.set_cookie("theme_bg", p.background, max_age=age)
        response.set_cookie("theme_panel", p.panel, max_age=age)

    def safe_back_url(request: Request) -> str:
        referer = request.headers.get("referer") or "/"
        if referer.startswith("/") and not referer.startswith("//"):
            return referer
        try:
            parsed = urlparse(referer)
            if parsed.path:
                return parsed.path + (f"?{parsed.query}" if parsed.query else "")
        except Exception:
            pass
        return "/"

    def studio_add_return_url(media_id: int, return_to: str | None) -> str:
        """Allowlist redirect after Add to Studio (no open redirects)."""
        raw = (return_to or "detail").strip()
        target = raw.lower()
        if target == "browse":
            return "/browse"
        if target == "studio":
            return "/studio"
        if target == "detail":
            return f"/media/{media_id}"
        # Internal relative Browse URL with filters (Variant A allowlist extension).
        if raw.startswith("/") and not raw.startswith("//") and "://" not in raw:
            parsed = urlparse(raw)
            if parsed.path in {"/browse", "/media", "/studio"}:
                return parsed.path + (f"?{parsed.query}" if parsed.query else "")
        return f"/media/{media_id}"

    def studio_bulk_return_url(return_to: str | None) -> str:
        """Allowlist redirect after Browse bulk Add to Studio."""
        raw = (return_to or "browse").strip()
        target = raw.lower()
        if target in {"browse", "studio"}:
            return f"/{target}"
        if raw.startswith("/") and not raw.startswith("//") and "://" not in raw:
            parsed = urlparse(raw)
            if parsed.path in {"/browse", "/media", "/studio"}:
                return parsed.path + (f"?{parsed.query}" if parsed.query else "")
        return "/browse"

    def append_query_params(url: str, **params: Any) -> str:
        """Append query params to an internal relative URL (no open redirects)."""
        parsed = urlparse(url)
        q = dict(parse_qsl(parsed.query, keep_blank_values=True))
        for key, value in params.items():
            if value is None or value == "":
                continue
            q[str(key)] = str(value)
        new_query = urlencode(q)
        return urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
        )

    def map_return_from_request(
        request: Request, media_id: int
    ) -> tuple[str | None, str]:
        """Build world-map return URL + detail qs when navigated from /map.

        Expects ``?from=map&lat=&lon=&zoom=`` (zoom optional). Returns
        ``(return_url, detail_qs)`` or ``(None, "")`` when not from the map.
        """
        qp = request.query_params
        if qp.get("from") != "map":
            return None, ""
        lat: float | None = None
        lon: float | None = None
        zoom: float | None = None
        try:
            if qp.get("lat") is not None and qp.get("lon") is not None:
                lat = float(qp["lat"])
                lon = float(qp["lon"])
                if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                    lat = lon = None
        except (TypeError, ValueError):
            lat = lon = None
        try:
            if qp.get("zoom") is not None:
                zoom = max(1.0, min(19.0, float(qp["zoom"])))
        except (TypeError, ValueError):
            zoom = None
        detail: dict[str, str] = {"from": "map"}
        ret: dict[str, str] = {"focus": str(media_id)}
        if lat is not None and lon is not None:
            lat_s, lon_s = f"{lat:.6f}", f"{lon:.6f}"
            detail["lat"] = lat_s
            detail["lon"] = lon_s
            ret["lat"] = lat_s
            ret["lon"] = lon_s
            if zoom is not None:
                zoom_s = f"{zoom:.2f}".rstrip("0").rstrip(".")
                detail["zoom"] = zoom_s
                ret["zoom"] = zoom_s
        return f"/map?{urlencode(ret)}", urlencode(detail)

    _BROWSE_RETURN_KEYS = (
        "sort",
        "order",
        "drone",
        "kind",
        "gps",
        "source",
        "flows",
        "sessions",
        "favorite",
        "q",
        "date_from",
        "date_to",
        "ask",
        "view",
        "page",
        "page_size",
        "tl",
    )

    def browse_detail_qs_from_request(request: Request) -> str:
        """QS for media detail links so detail can return to the same browse filters."""
        items: list[tuple[str, str]] = [("from", "browse")]
        qp = request.query_params
        for key in _BROWSE_RETURN_KEYS:
            val = qp.get(key)
            if val:
                items.append((key, val))
        return urlencode(items)

    def _browse_filters_from_mapping(mapping: dict[str, str]) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        for key in _BROWSE_RETURN_KEYS:
            val = mapping.get(key)
            if val:
                items.append((key, str(val)))
        return items

    def _browse_return_pair(
        filter_items: list[tuple[str, str]],
    ) -> tuple[str, str]:
        detail = [("from", "browse"), *filter_items]
        detail_qs = urlencode(detail)
        if filter_items:
            return f"/browse?{urlencode(filter_items)}", detail_qs
        return "/browse", detail_qs

    def browse_return_from_referer(request: Request) -> tuple[str | None, str]:
        """Fallback when detail was opened from /browse without ``from=browse`` qs."""
        referer = request.headers.get("referer") or ""
        if not referer:
            return None, ""
        try:
            parsed = urlparse(referer)
        except Exception:
            return None, ""
        path = parsed.path or ""
        if parsed.netloc:
            host = (request.headers.get("host") or "").split(":")[0].lower()
            ref_host = (parsed.hostname or "").lower()
            if ref_host and host and ref_host != host and ref_host not in {
                "testserver",
                "127.0.0.1",
                "localhost",
            }:
                return None, ""
        if path not in {"/browse", "/media"}:
            return None, ""
        filters = _browse_filters_from_mapping(
            dict(parse_qsl(parsed.query, keep_blank_values=False))
        )
        return _browse_return_pair(filters)

    def browse_return_from_request(request: Request) -> tuple[str | None, str]:
        """Build browse return URL + detail qs when navigated from /browse.

        Prefers ``?from=browse`` (+ filter params). Falls back to a same-origin
        Referer of ``/browse`` or ``/media`` so Nav/Zurück still work if the
        detail link omitted the return query. Returns ``(return_url, detail_qs)``
        or ``(None, "")`` when not from browse.
        """
        qp = request.query_params
        if qp.get("from") == "map":
            return None, ""
        if qp.get("from") == "browse":
            return _browse_return_pair(_browse_filters_from_mapping(dict(qp)))
        return browse_return_from_referer(request)

    def ctx(request: Request, **extra: Any) -> dict[str, Any]:
        lang = lang_from_request(request)
        _ = get_translator(lang)
        theme = theme_from_request(request)
        return {
            "request": request,
            "lang": lang,
            "langs": SUPPORTED_LANGS,
            "_": _,
            "version": installed_version(),
            "check_updates": get_check_updates(),
            "download_url": OFFICIAL_DOWNLOAD_URL,
            "stats": db.stats(),
            "theme": theme.mode,
            "theme_accent": theme.accent,
            "theme_bg": theme.background,
            "theme_panel": theme.panel,
            "theme_style": custom_css_vars(theme) if theme.mode == "custom" else "",
            "nav_active": "",
            "browse_return_url": None,
            "offline_root_ids": offline_root_ids(db),
            **extra,
        }

    def render(request: Request, name: str, status_code: int = 200, **extra: Any) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            name,
            ctx(request, **extra),
            status_code=status_code,
        )

    def file_response(path: Path) -> FileResponse:
        # Starlette FileResponse supports HTTP Range (partial content) and
        # streams in chunks — no full-file read into memory.
        media_type = MIME_BY_SUFFIX.get(path.suffix.lower(), "application/octet-stream")
        # Omit filename for images: some WebView2 builds treat
        # Content-Disposition filename=… as a download and skip <img> display.
        kwargs: dict[str, Any] = {
            "media_type": media_type,
            "content_disposition_type": "inline",
            "headers": {
                "Accept-Ranges": "bytes",
                "Cache-Control": "private, max-age=3600",
            },
        }
        if not media_type.startswith("image/"):
            kwargs["filename"] = path.name
        return FileResponse(path, **kwargs)

    def _music_track_client_payload(project_id: int, clip: Any) -> dict[str, Any]:
        path = Path(clip.file_path)
        available = path.is_file()
        token = "0"
        if available:
            try:
                st = path.stat()
                token = hashlib.sha256(
                    f"{clip.id}:{clip.file_path}:{int(st.st_mtime)}:{st.st_size}".encode()
                ).hexdigest()[:16]
            except OSError:
                token = "0"
        return {
            "id": clip.id,
            "position": clip.position,
            "available": available,
            "display_name": clip.display_name,
            "volume": clip.volume,
            "fade_in_s": clip.fade_in_s,
            "fade_out_s": clip.fade_out_s,
            "loop": bool(clip.loop),
            "duration_s": clip.duration_s,
            "stream_url": (
                f"/api/studio/projects/{project_id}/music/{clip.id}/stream?v={token}"
                if available
                else None
            ),
        }

    def _music_tracks_client_payload(project_id: int) -> dict[str, Any]:
        project = db.get_studio_project(project_id)
        return {
            "music_start_s": project.music_start_s if project is not None else 0.0,
            "tracks": [
                _music_track_client_payload(project_id, clip)
                for clip in db.list_studio_music(project_id)
            ]
        }

    def _studio_summary(project_id: int, items: list[Any]) -> Any:
        return summarize_studio_items(
            items,
            soundtrack_once_s=soundtrack_once_s(db.list_studio_music(project_id)),
        )

    def _raise_music_value_error(exc: ValueError) -> NoReturn:
        msg = str(exc)
        if msg == "music_limit":
            raise HTTPException(status_code=409, detail="music_limit") from exc
        if msg == "loop_single_only":
            raise HTTPException(status_code=400, detail="loop_single_only") from exc
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=400, detail=msg) from exc

    def _music_path_from_payload(payload: dict[str, Any]) -> Path:
        from orga_drone.export.music_mix import validate_music_file_path

        if not isinstance(payload.get("path"), str):
            raise HTTPException(status_code=400, detail="path is required")
        try:
            return validate_music_file_path(payload["path"])
        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail="The selected music file is no longer available.",
            ) from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        """Home — entry actions and a hero from an already cached thumbnail."""
        recent = db.list_media(sort="recorded_at", order="desc", limit=8)
        favorites = db.list_media(sort="recorded_at", order="desc", favorite=True, limit=8)
        hero_pool = db.list_media(sort="recorded_at", order="desc", limit=24)
        hero_media_id = pick_home_media_id(
            hero_pool,
            settings.data_dir,
            file_ready=lambda item: resolve_media_file(db, item),
        )
        cached_ids = [
            item.id
            for item in [*recent, *favorites]
            if resolve_media_file(db, item) is not None
            and cached_thumbnail(settings.data_dir, item.id) is not None
        ]
        return render(
            request,
            "dashboard.html",
            recent=recent,
            favorites=favorites,
            hero_media_id=hero_media_id,
            cached_media_ids=cached_ids,
            continue_project=db.get_open_studio_project(),
            nav_active="dashboard",
        )

    @app.get("/dashboard")
    async def dashboard_alias() -> RedirectResponse:
        return RedirectResponse(url="/", status_code=303)

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request) -> HTMLResponse:
        from orga_drone.desktop import can_reveal_local_file

        sizes = cache_sizes(settings.data_dir)
        lut_entries = [entry.as_dict() for entry in list_catalog(db, settings.data_dir)]
        return render(
            request,
            "settings.html",
            data_dir=settings.data_dir,
            db_path=settings.db_path,
            thumbs_dir=settings.data_dir / "thumbs",
            tiles_dir=settings.data_dir / "osm-tiles",
            luts_dir=lut_asset_dir(settings.data_dir),
            cache_total=format_cache_bytes(sizes["total"]),
            cache_thumbs=format_cache_bytes(sizes["thumbs"]),
            cache_tiles=format_cache_bytes(sizes["osm-tiles"]),
            library_roots=db.list_roots(),
            cache_cleared=request.query_params.get("cache") == "cleared",
            lut_catalog=lut_entries,
            lut_folder_reveal=can_reveal_local_file(),
            nav_active="settings",
        )

    @app.post("/settings/cache/clear")
    async def clear_cache() -> RedirectResponse:
        clear_regenerable_cache(settings.data_dir)
        return RedirectResponse(url="/settings?cache=cleared", status_code=303)

    @app.get("/browse", response_class=HTMLResponse)
    @app.get("/media", response_class=HTMLResponse)
    async def browse(
        request: Request,
        sort: str = Query("recorded_at"),
        order: str = Query("desc"),
        drone: str | None = None,
        kind: str | None = None,
        gps: str | None = None,
        source: str | None = None,
        flows: str | None = None,
        sessions: str | None = None,
        favorite: str | None = None,
        q: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        ask: str | None = None,
        view: str | None = None,
        page: int = Query(1, ge=1),
        page_size: str | None = None,
        tl: str | None = None,
        msg: str | None = None,
        added: int | None = None,
        skipped: int | None = None,
    ) -> HTMLResponse:
        has_gps = {"yes": True, "no": False}.get(gps or "")
        flows_only = {"yes": True, "no": False}.get(flows or "")
        sessions_only = {"yes": True, "no": False}.get(sessions or "")
        ask_text = (ask or "").strip()
        parsed = parse_natural_query(ask_text) if ask_text else MediaSearch()
        fav_explicit = {"yes": True, "no": False}.get(favorite or "")
        search = merge_search(
            parsed,
            kind=kind or None,
            date_from=date_from,
            date_to=date_to,
            q=q,
            favorite=fav_explicit,
        )
        favorite_only = (
            search.favorite
            if fav_explicit is not None or search.favorite is not None
            else None
        )
        current_view = view_from_request(request, view)
        focus = parse_timeline_focus(tl) if current_view == "timeline" else None
        recorded_span = focus.token if focus is not None else None
        timeline_order = "asc" if order.lower() == "asc" else "desc"
        resolved_kind = search.kind
        resolved_q = search.effective_q()
        resolved_from = search.date_from
        resolved_to = search.date_to
        list_kwargs: dict[str, Any] = {
            "sort": sort,
            "order": order,
            "drone": drone or None,
            "kind": resolved_kind,
            "source": source or None,
            "has_gps": has_gps,
            "flows_only": flows_only,
            "sessions_only": sessions_only,
            "favorite": favorite_only,
            "q": resolved_q,
            "date_from": resolved_from,
            "date_to": resolved_to,
            "recorded_span": recorded_span,
            "date_order": timeline_order if current_view == "timeline" else None,
        }
        total = db.count_media(
            drone=list_kwargs["drone"],
            kind=list_kwargs["kind"],
            source=list_kwargs["source"],
            has_gps=list_kwargs["has_gps"],
            flows_only=list_kwargs["flows_only"],
            sessions_only=list_kwargs["sessions_only"],
            favorite=list_kwargs["favorite"],
            q=list_kwargs["q"],
            date_from=list_kwargs["date_from"],
            date_to=list_kwargs["date_to"],
            recorded_span=list_kwargs["recorded_span"],
        )
        size = browse_resolve_page_size(page_size)
        pagination = browse_pagination(total=total, page=page, page_size=size)
        items = db.list_media(
            **list_kwargs,
            limit=pagination["page_size"],
            offset=pagination["offset"],
        )
        open_project = db.resolve_studio_page_project()
        studio_paths = (
            db.studio_paths_among(
                [it.path for it in items], project_id=open_project.id
            )
            if open_project is not None
            else set()
        )
        favorite_filter = favorite or ""
        if not favorite_filter and search.favorite is True:
            favorite_filter = "yes"
        filters = {
            "sort": sort,
            "order": order,
            "drone": drone or "",
            "kind": resolved_kind or "",
            "source": source or "",
            "gps": gps or "",
            "flows": flows or "",
            "sessions": sessions or "",
            "favorite": favorite_filter,
            "q": resolved_q or "",
            "date_from": resolved_from or "",
            "date_to": resolved_to or "",
            "ask": ask_text,
            "view": current_view,
            "page_size": str(pagination["page_size"]),
            "tl": recorded_span or "",
        }

        def timeline_href(token: str | None) -> str:
            payload = dict(filters)
            payload["view"] = "timeline"
            payload["tl"] = token or ""
            return "/browse?" + browse_filter_query(payload)

        timeline_nav = None
        timeline_groups: list[Any] = []
        if current_view == "timeline":
            day_counts = db.timeline_day_counts(
                drone=list_kwargs["drone"],
                kind=list_kwargs["kind"],
                source=list_kwargs["source"],
                has_gps=list_kwargs["has_gps"],
                flows_only=list_kwargs["flows_only"],
                sessions_only=list_kwargs["sessions_only"],
                favorite=list_kwargs["favorite"],
                q=list_kwargs["q"],
                date_from=list_kwargs["date_from"],
                date_to=list_kwargs["date_to"],
            )
            timeline_nav = build_timeline_nav(
                day_counts,
                active=focus,
                order=timeline_order,
                href_for=timeline_href,
            )
            timeline_groups = group_timeline_page(items, href_for=timeline_href)
        response = render(
            request,
            "index.html",
            items=items,
            studio_paths=studio_paths,
            drones=db.distinct_drones(),
            source_buckets=db.source_bucket_counts(),
            view=current_view,
            nav_active="browse",
            browse_detail_qs=browse_detail_qs_from_request(request),
            ask_summary=search.summary_parts() if ask_text else [],
            filters=filters,
            browse_page_sizes=BROWSE_PAGE_SIZES,
            pagination=pagination,
            browse_qs=browse_filter_query(filters, page=pagination["page"]),
            browse_qs_prev=browse_filter_query(
                filters, page=pagination["prev_page"]
            ),
            browse_qs_next=browse_filter_query(
                filters, page=pagination["next_page"]
            ),
            flash_msg=msg,
            flash_added=added,
            flash_skipped=skipped,
            timeline_nav=timeline_nav,
            timeline_groups=timeline_groups,
        )
        if view in {"grid", "list", "timeline"}:
            response.set_cookie("view", view, max_age=365 * 24 * 3600)
        return response

    @app.post("/api/search")
    async def api_search(request: Request) -> dict[str, Any]:
        """Structured / NL media search (JSON body). Same filters as Browse."""
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        search = media_search_from_payload(payload)
        sort = str(payload.get("sort") or "recorded_at")
        order = str(payload.get("order") or "desc")
        items = db.list_media(
            sort=sort,
            order=order,
            drone=(str(payload["drone"]).strip() or None) if payload.get("drone") else None,
            kind=search.kind,
            source=(str(payload["source"]).strip() or None) if payload.get("source") else None,
            favorite=search.favorite,
            q=search.effective_q(),
            date_from=search.date_from,
            date_to=search.date_to,
        )
        limit = search.limit
        if limit is not None and limit > 0:
            items = items[:limit]
        return {
            "filters": search.to_dict(),
            "summary": search.summary_parts(),
            "count": len(items),
            "items": [
                {
                    "id": it.id,
                    "kind": it.kind,
                    "filename": it.filename,
                    "recorded_at": it.recorded_at,
                    "path": it.path,
                    "drone_model": it.drone_model,
                    "tags": it.tags,
                    "auto_tags": it.auto_tags,
                    "place": it.place,
                    "favorite": it.favorite,
                    "stars": it.stars,
                }
                for it in items
            ],
        }

    @app.get("/map", response_class=HTMLResponse)
    async def world_map(request: Request) -> HTMLResponse:
        return render(request, "map.html", nav_active="map")

    @app.get("/api/geo/media")
    async def api_geo_media(
        north: float | None = Query(None),
        south: float | None = Query(None),
        east: float | None = Query(None),
        west: float | None = Query(None),
        zoom: float | None = Query(None),
        include_noloc: int = Query(0),
    ) -> dict[str, Any]:
        """GPS media points for the world map (optional bbox + without-location list)."""
        bbox = None
        if None not in (north, south, east, west):
            bbox = (float(north), float(south), float(east), float(west))  # type: ignore[arg-type]
        points = db.list_geo_media(
            north=bbox[0] if bbox else None,
            south=bbox[1] if bbox else None,
            east=bbox[2] if bbox else None,
            west=bbox[3] if bbox else None,
            with_gps=True,
        )
        without: list[dict[str, Any]] = []
        if include_noloc:
            without = db.list_geo_media(with_gps=False, limit=200)
        stats = db.stats()
        offline = offline_root_ids(db)
        for row in points:
            row["source_offline"] = int(row["root_id"]) in offline
        for row in without:
            row["source_offline"] = int(row["root_id"]) in offline
        return {
            "items": points,
            "without_location": without,
            "count": len(points),
            "without_count": len(without),
            "totals": {
                "with_gps": stats.get("with_gps", 0),
                "media": stats["videos"] + stats["photos"],
            },
            "zoom": zoom,
        }

    @app.get("/media/{media_id}", response_class=HTMLResponse)
    async def media_detail(
        request: Request,
        media_id: int,
        msg: str | None = None,
        error: str | None = None,
        tab: str | None = None,
    ) -> HTMLResponse:
        item = db.get_media(media_id)
        if not item:
            return render(request, "error.html", status_code=404, message="Not found")
        if item.kind == "video" and item.duration_s is None:
            filled = db.fill_video_duration_if_missing(item.id)
            if filled is not None:
                item.duration_s = filled
        clips = db.flow_clips(item.flow_id) if item.flow_id else []
        multi_flow = bool(item.flow_id and item.clip_count and item.clip_count > 1)
        if not multi_flow and item.flow_id and len(clips) > 1:
            multi_flow = True
        session_clips = db.session_clips(item.session_id) if item.session_id else []
        multi_session = bool(
            item.session_id
            and item.session_video_count
            and item.session_video_count > 1
        )
        if not multi_session and item.session_id:
            video_n = sum(1 for c in session_clips if c.kind == "video")
            multi_session = video_n > 1

        # Prefer multi-clip session; fall back to multi-clip flow for the flight tab.
        if multi_session:
            flight_items = session_clips
            flight_source = "session"
        elif multi_flow:
            flight_items = clips
            flight_source = "flow"
        else:
            flight_items = []
            flight_source = None
        show_view_tabs = len(flight_items) > 1
        active_tab = normalize_detail_tab(tab) if show_view_tabs else "clip"
        if active_tab == "flight" and not show_view_tabs:
            active_tab = "clip"

        flight_playlist = build_flight_playlist(db, flight_items) if show_view_tabs else []
        playlist_index_by_id = {int(e["id"]): i for i, e in enumerate(flight_playlist)}
        flight_track: list[dict[str, Any]] = []
        flight_duration: float | None = None
        if active_tab == "flight" and flight_items:
            flight_track, total_s = concat_clip_tracks(flight_items)
            flight_duration = total_s if total_s > 0 else None

        track = track_from_json(item.track_json)
        display_track = flight_track if active_tab == "flight" and flight_track else track
        display_duration = (
            flight_duration if active_tab == "flight" and flight_duration is not None else item.duration_s
        )

        map_lat, map_lon = (
            flight_map_center(item, flight_items, display_track)
            if active_tab == "flight"
            else (item.latitude, item.longitude)
        )
        map_link = osm_link(map_lat, map_lon) if map_lat is not None and map_lon is not None else None
        show_map = map_lat is not None and map_lon is not None

        media_path = resolve_media_file(db, item)
        proxy_path = resolve_proxy_file(db, item) if item.kind == "video" else None
        play_id = item.id
        play_has_proxy = proxy_path is not None
        play_can = media_path is not None
        play_start_index = 0
        # Browsers cannot show HEIC/HEIF/DNG in <img>; map thumbs are JPEG — detail
        # must use a converted preview for those formats.
        photo_src: str | None = None
        if item.kind == "photo" and media_path is not None:
            if browser_can_display_photo(media_path):
                photo_src = f"/media/{item.id}/stream"
            else:
                photo_src = f"/media/{item.id}/preview"
        if active_tab == "flight" and flight_playlist:
            for i, entry in enumerate(flight_playlist):
                if entry["id"] == item.id:
                    play_start_index = i
                    break
            start_entry = flight_playlist[play_start_index]
            play_id = int(start_entry["id"])
            play_has_proxy = bool(start_entry["has_proxy"])
            play_can = bool(start_entry["can_play"])

        stem = Path(item.filename).stem
        source_offline = item.root_id in offline_root_ids(db)
        item_exportable = (
            item.kind in {"photo", "video"}
            and media_path is not None
            and not source_offline
        )
        map_return_url, map_from_qs = map_return_from_request(request, item.id)
        browse_return_url, browse_from_qs = browse_return_from_request(request)
        return_qs = map_from_qs or browse_from_qs
        open_detail = db.resolve_studio_page_project()
        in_studio = (
            db.is_in_studio(item.path, project_id=open_detail.id)
            if open_detail is not None
            else False
        )
        media_albums = db.albums_for_path(item.path)
        member_ids = {album.id for album in media_albums}
        albums_available = [
            album for album in db.list_albums() if album.id not in member_ids
        ]
        return render(
            request,
            "detail.html",
            item=item,
            clips=clips,
            session_clips=session_clips if multi_session else [],
            flight_items=flight_items if show_view_tabs else [],
            flight_playlist=flight_playlist,
            flight_playlist_json=json.dumps(flight_playlist),
            playlist_index_by_id=playlist_index_by_id,
            flight_source=flight_source,
            show_view_tabs=show_view_tabs,
            active_tab=active_tab,
            track=display_track,
            map_lat=map_lat,
            map_lon=map_lon,
            map_duration=display_duration,
            show_map=show_map,
            osm_url=map_link,
            can_play=play_can,
            has_proxy=play_has_proxy,
            play_id=play_id,
            play_start_index=play_start_index,
            photo_src=photo_src,
            can_merge=multi_flow and item.kind == "video",
            ffmpeg_ok=ffmpeg_available(),
            merge_default_name=default_merge_name(item) if item.kind == "video" else "",
            rename_stem=stem,
            flash_msg=msg,
            flash_error=error,
            map_return_url=map_return_url,
            map_from_qs=map_from_qs,
            browse_return_url=browse_return_url,
            browse_from_qs=browse_from_qs,
            return_qs=return_qs,
            in_studio=in_studio,
            item_exportable=item_exportable,
            image_adjust_model=image_adjust_preview_model(),
            quick_looks_model=quick_looks_preview_model(),
            photo_adjust=(
                db.get_image_adjust(item.path).as_dict() if item.kind == "photo" else None
            ),
            photo_look=(
                db.get_photo_look_id(item.path) if item.kind == "photo" else ""
            ),
            media_albums=media_albums,
            albums_available=albums_available,
        )

    def studio_gallery_cards() -> list[dict[str, Any]]:
        """Gallery rows in last-edited order. Thumbs are existing files only."""
        cards: list[dict[str, Any]] = []
        for project in db.list_studio_projects():
            items = db.list_studio_items(project.id)
            summary = summarize_studio_items(items)
            thumb_id: int | None = None
            for item in items:
                if item.item_kind == "title_card" or item.source_media_id is None:
                    continue
                media = db.get_media(item.source_media_id)
                if media is None or resolve_media_file(db, media) is None:
                    continue
                if cached_thumbnail(settings.data_dir, media.id) is None:
                    continue
                thumb_id = media.id
                break
            cards.append(
                {
                    "id": project.id,
                    "title": project.title,
                    "updated_at": project.updated_at.replace("T", " "),
                    "duration_label": summary.estimated_total_label,
                    "thumb_id": thumb_id,
                }
            )
        return cards

    @app.get("/studio/projects", response_class=HTMLResponse)
    async def studio_projects_page(
        request: Request, msg: str | None = None
    ) -> HTMLResponse:
        return render(
            request,
            "studio_projects.html",
            projects=studio_gallery_cards(),
            nav_active="studio",
            flash_msg=msg,
        )

    @app.post("/studio/projects")
    async def studio_project_create(request: Request) -> RedirectResponse:
        """Create an empty project and open it. Never reuses another project."""
        title = get_translator(lang_from_request(request))("Your story")
        project = db.create_studio_project(title)
        db.set_open_studio_project_id(project.id)
        return RedirectResponse(url="/studio", status_code=303)

    @app.post("/studio/projects/{project_id}/delete")
    async def studio_project_delete(project_id: int) -> RedirectResponse:
        deleted = db.delete_studio_project(project_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="studio project not found")
        return RedirectResponse(url="/studio/projects", status_code=303)

    @app.get("/studio", response_class=HTMLResponse)
    async def studio_page(
        request: Request,
        msg: str | None = None,
        project_id: int | None = None,
        select: int | None = None,
        focus: str | None = None,
    ) -> Response:
        if project_id is not None:
            target = db.get_studio_project(project_id)
            if target is None:
                raise HTTPException(status_code=404, detail="studio project not found")
            db.set_open_studio_project_id(target.id)
            suffix = f"?msg={msg}" if msg else ""
            return RedirectResponse(url=f"/studio{suffix}", status_code=303)

        project = db.resolve_studio_page_project()
        if project is None:
            gallery_url = "/studio/projects"
            if msg:
                gallery_url = f"{gallery_url}?msg={msg}"
            return RedirectResponse(url=gallery_url, status_code=303)
        projects = db.list_studio_projects()
        studio_mode = "editor"
        items = db.list_studio_items(project.id) if project is not None else []
        for it in items:
            if (it.kind or "") != "video" or it.duration_s is not None:
                continue
            if it.source_media_id is None:
                continue
            filled = db.fill_video_duration_if_missing(it.source_media_id)
            if filled is not None:
                it.duration_s = filled
        soundtrack_once = (
            soundtrack_once_s(db.list_studio_music(project.id))
            if project is not None
            else None
        )
        forward_resolution = resolve_forward_loop(items, soundtrack_once)
        summary = summarize_studio_items(items, soundtrack_once_s=soundtrack_once)
        lang = lang_from_request(request)
        item_display: list[dict[str, Any]] = []
        favorite_media: list[Any] = []
        applied_by_id: dict[int, Any] = {}
        if project is not None:
            _durs, applied_list, source_indexes = apply_for_items(
                items, duration_overrides=forward_resolution.overrides
            )
            for seq_i, item_idx in enumerate(source_indexes):
                if seq_i < len(applied_list):
                    applied_by_id[items[item_idx].id] = applied_list[seq_i]
            for it in items:
                repeats = (
                    section_repeats_from_effect_settings(it.effect_settings)
                    if (it.kind or "") == "video"
                    else 1
                )
                one_play = effective_seconds(
                    kind=it.kind or "unknown",
                    photo_duration_s=it.photo_duration_s,
                    duration_s=it.duration_s,
                    available=it.available,
                    source_in_s=it.source_start,
                    source_out_s=it.source_end,
                    card_duration_s=it.card_duration_s,
                    section_repeats=1,
                )
                seconds: float | None
                if (
                    forward_resolution.active
                    and forward_resolution.item_id == it.id
                    and forward_resolution.total_s is not None
                ):
                    seconds = float(forward_resolution.total_s)
                else:
                    seconds = item_effective_seconds(it)
                stream_url = ""
                proxy_url = ""
                preview_url = ""
                has_proxy = False
                can_play = False
                display_title = ""
                display_subtitle = ""
                media_row = None
                media_path = None
                color_profile_hint = ""
                hud_state = empty_hud_state()
                if it.kind == TITLE_CARD_KIND:
                    display_title, display_subtitle = display_lines(
                        it.title_text, it.subtitle_text, lang
                    )
                elif it.available and it.media_id is not None:
                    media_row = db.get_media(it.media_id)
                    if media_row is not None:
                        media_path = resolve_media_file(db, media_row)
                        can_play = media_path is not None
                        if media_path is not None:
                            stream_url = f"/media/{it.media_id}/stream"
                            kind = (
                                it.kind
                                if it.kind in {"photo", "video"}
                                else media_row.kind
                            )
                            if kind == "video":
                                hint = color_profile_hint_from_srt(media_path)
                                if hint:
                                    color_profile_hint = hint
                                proxy_path = resolve_proxy_file(db, media_row)
                                has_proxy = proxy_path is not None
                                if has_proxy:
                                    proxy_url = f"/media/{it.media_id}/proxy"
                            if kind == "video" and media_path is not None:
                                hud_state = hud_client_state(
                                    media_path,
                                    effect_settings=it.effect_settings,
                                    source_start_s=it.source_start,
                                    source_end_s=it.source_end,
                                    media_duration_s=None,
                                    fallback_duration_s=seconds,
                                )
                            elif kind == "photo":
                                if browser_can_display_photo(media_path):
                                    preview_url = stream_url
                                else:
                                    preview_url = f"/media/{it.media_id}/preview"
                                if not preview_url:
                                    preview_url = f"/media/{it.media_id}/thumb"
                color_anim_row = color_animation_from_effect_settings(it.effect_settings)
                item_display.append(
                    {
                        "item": it,
                        "section_repeats": repeats,
                        "forward_loop": clip_forward_loop_view(
                            it, forward_resolution, soundtrack_once
                        ),
                        "effective_duration_s": seconds,
                        "display_duration_s": (
                            it.card_duration_s
                            if it.kind == TITLE_CARD_KIND and it.card_duration_s is not None
                            else (
                                it.photo_duration_s
                                if it.kind == "photo" and it.photo_duration_s is not None
                                else (
                                    DEFAULT_PHOTO_DURATION_S
                                    if it.kind == "photo"
                                    else seconds
                                )
                            )
                        ),
                        "stream_url": stream_url,
                        "proxy_url": proxy_url,
                        "preview_url": preview_url,
                        "has_proxy": has_proxy,
                        "can_play": can_play,
                        "display_title": display_title,
                        "display_subtitle": display_subtitle,
                        "image_adjust": image_adjust_from_effect_settings(
                            it.effect_settings
                        ).as_dict(),
                        "color_look": color_look_from_effect_settings(
                            it.effect_settings
                        ).as_dict(),
                        "quick_look": look_id_from_effect_settings(it.effect_settings),
                        "detail": detail_from_effect_settings(it.effect_settings).as_dict(),
                        "color_profile_hint": color_profile_hint,
                        "saturation_ramp": saturation_ramp_from_effect_settings(
                            it.effect_settings
                        ).as_dict(),
                        "color_animation": (
                            color_anim_row.as_dict() if color_anim_row.is_active else None
                        ),
                        "overlays": [
                            item.as_dict()
                            for item in overlays_from_effect_settings(
                                it.effect_settings,
                                duration_s=float(
                                    (one_play if it.kind == "video" and one_play else None)
                                    or seconds
                                    or it.photo_duration_s
                                    or DEFAULT_PHOTO_DURATION_S
                                ),
                            )
                        ]
                        if it.kind in {"photo", "video"}
                        else [],
                        "masks": [
                            mask.as_dict()
                            for mask in masks_from_effect_settings(it.effect_settings)
                        ]
                        if it.kind in {"photo", "video"}
                        else [],
                        "frame": frame_from_effect_settings(it.effect_settings).as_dict(),
                        "zoom_bar": stored_lane(it.effect_settings)["zoom_bar"],
                        "slow_bar": stored_lane(it.effect_settings)["slow_bar"],
                        "clip_audio": detached_audio_from_effect_settings(
                            it.effect_settings
                        ).as_dict(),
                        "map": map_from_effect_settings(it.effect_settings).as_dict(),
                        "gps": (
                            route_preview(
                                gps_from_stored(
                                    track_from_json(media_row.track_json),
                                    latitude=media_row.latitude,
                                    longitude=media_row.longitude,
                                ),
                                media_duration_s=media_row.duration_s,
                            )
                            if media_row is not None and it.kind in {"photo", "video"}
                            else {"line": [], "marker": [], "tiles": []}
                        ),
                        "hud": hud_state,
                        "stored_transition": normalize_type(it.transition),
                        "stored_transition_duration_s": it.transition_duration_s,
                        "applied_transition": applied_by_id.get(it.id),
                        "clip_flex_s": clip_flex_s(
                            seconds or 0.0, applied_by_id.get(it.id)
                        ),
                    }
                )
            studio_paths = {it.media_path for it in items if it.media_path}
            favorite_media = [
                fav
                for fav in db.list_media(
                    favorite=True, sort="recorded_at", order="desc", limit=48
                )
                if fav.path not in studio_paths
            ]
        music_payload = (
            _music_tracks_client_payload(project.id)
            if project is not None
            else {"tracks": []}
        )
        studio_originals: list[dict[str, Any]] = []
        if project is not None:
            db.sync_studio_originals(project.id)
            for original in db.list_studio_originals(project.id):
                media_id = original["media_id"]
                duration_s = original["duration_s"]
                if media_id is not None and duration_s is None:
                    filled = db.fill_video_duration_if_missing(int(media_id))
                    if filled is not None:
                        duration_s = filled
                stream_url = ""
                proxy_url = ""
                has_proxy = False
                can_play = False
                available = media_id is not None
                if media_id is not None:
                    media_row = db.get_media(int(media_id))
                    if media_row is not None and resolve_media_file(db, media_row) is not None:
                        can_play = True
                        stream_url = f"/media/{media_id}/stream"
                        if media_row.kind == "video" and resolve_proxy_file(db, media_row) is not None:
                            has_proxy = True
                            proxy_url = f"/media/{media_id}/proxy"
                    elif media_row is None:
                        available = False
                studio_originals.append(
                    {
                        **original,
                        "duration_s": duration_s,
                        "available": available,
                        "can_play": can_play and duration_s is not None and float(duration_s) > 0,
                        "stream_url": stream_url,
                        "proxy_url": proxy_url,
                        "has_proxy": has_proxy,
                    }
                )
        story_history = history_flags(project.id if project is not None else None)
        lut_catalog = [entry.as_dict() for entry in list_catalog(db, settings.data_dir)]
        return render(
            request,
            "studio.html",
            items=items,
            item_display=item_display,
            project=project,
            projects=projects,
            studio_mode=studio_mode,
            summary=summary,
            default_photo_duration_s=DEFAULT_PHOTO_DURATION_S,
            image_adjust_model=image_adjust_preview_model(),
            color_look_model=color_look_preview_model(),
            color_animation_model=color_animation_preview_model(),
            lut_catalog=lut_catalog,
            quick_looks_model=quick_looks_preview_model(),
            detail_model=detail_preview_model(),
            frame_model=frame_preview_model(),
            mask_model=mask_preview_model(),
            overlay_model=overlay_preview_model(),
            map_model=map_preview_model(),
            favorite_media=favorite_media,
            studio_originals=studio_originals,
            music_payload=music_payload,
            can_undo=story_history["can_undo"],
            can_redo=story_history["can_redo"],
            flash_msg=msg,
            nav_active="studio",
            select_id=select,
            focus_field=focus,
        )

    def _studio_project_json(project: Any) -> dict[str, Any]:
        return {
            "id": project.id,
            "title": project.title,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
            "music_start_s": project.music_start_s,
            "clip_count": getattr(project, "clip_count", 0),
        }

    @app.get("/api/studio/projects")
    async def api_studio_projects_list() -> JSONResponse:
        projects = db.list_studio_projects()
        opened = db.get_open_studio_project()
        return JSONResponse(
            {
                "ok": True,
                "current_id": opened.id if opened is not None else None,
                "projects": [_studio_project_json(p) for p in projects],
            }
        )

    @app.post("/api/studio/projects/{project_id}/open")
    async def api_studio_project_open(project_id: int) -> JSONResponse:
        project = db.get_studio_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="studio project not found")
        db.set_open_studio_project_id(project.id)
        return JSONResponse(
            {"ok": True, "id": project.id, "title": project.title}
        )

    def _require_studio_project(project_id: int):
        project = db.get_studio_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="studio project not found")
        return project

    @app.get("/api/studio/projects/{project_id}/music")
    async def api_studio_music_get(project_id: int) -> JSONResponse:
        _require_studio_project(project_id)
        return JSONResponse({"ok": True, **_music_tracks_client_payload(project_id)})

    @app.patch("/api/studio/projects/{project_id}/music-start")
    async def api_studio_music_start_patch(
        project_id: int, request: Request
    ) -> JSONResponse:
        _require_studio_project(project_id)
        try:
            payload = await request.json()
        except Exception:
            payload = None
        raw = payload.get("start_s") if isinstance(payload, dict) else None
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            raise HTTPException(status_code=400, detail="start_s must be a number")
        try:
            with story_edit(db, project_id, group=_history_group(request)):
                project = db.set_studio_music_start_s(project_id, float(raw))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "music_start_s": project.music_start_s})

    @app.post("/api/studio/projects/{project_id}/music")
    async def api_studio_music_post(project_id: int, request: Request) -> JSONResponse:
        _require_studio_project(project_id)
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        path = _music_path_from_payload(payload)
        try:
            db.append_studio_music(project_id, str(path))
        except ValueError as exc:
            _raise_music_value_error(exc)
        return JSONResponse({"ok": True, **_music_tracks_client_payload(project_id)})

    @app.put("/api/studio/projects/{project_id}/music/reorder")
    async def api_studio_music_reorder(project_id: int, request: Request) -> JSONResponse:
        _require_studio_project(project_id)
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict) or not isinstance(payload.get("ids"), list):
            raise HTTPException(status_code=400, detail="ids is required")
        ids: list[int] = []
        for raw in payload["ids"]:
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="ids must be integers") from None
        try:
            db.reorder_studio_music(project_id, ids)
        except ValueError as exc:
            _raise_music_value_error(exc)
        return JSONResponse({"ok": True, **_music_tracks_client_payload(project_id)})

    @app.patch("/api/studio/projects/{project_id}/music/{clip_id}")
    async def api_studio_music_patch(
        project_id: int, clip_id: int, request: Request
    ) -> JSONResponse:
        _require_studio_project(project_id)
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        kwargs: dict[str, Any] = {}
        if "volume" in payload:
            try:
                kwargs["volume"] = float(payload["volume"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="volume must be a number") from None
        if "fade_in_s" in payload:
            try:
                kwargs["fade_in_s"] = float(payload["fade_in_s"])
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400, detail="fade_in_s must be a number"
                ) from None
        if "fade_out_s" in payload:
            try:
                kwargs["fade_out_s"] = float(payload["fade_out_s"])
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400, detail="fade_out_s must be a number"
                ) from None
        if "loop" in payload:
            kwargs["loop"] = bool(payload["loop"])
        if "path" in payload:
            kwargs["file_path"] = str(_music_path_from_payload(payload))
        try:
            db.patch_studio_music_clip(project_id, clip_id, **kwargs)
        except ValueError as exc:
            _raise_music_value_error(exc)
        return JSONResponse({"ok": True, **_music_tracks_client_payload(project_id)})

    @app.delete("/api/studio/projects/{project_id}/music/{clip_id}")
    async def api_studio_music_delete(project_id: int, clip_id: int) -> JSONResponse:
        _require_studio_project(project_id)
        if not db.delete_studio_music_clip(project_id, clip_id):
            raise HTTPException(status_code=404, detail="studio music not found")
        return JSONResponse({"ok": True, **_music_tracks_client_payload(project_id)})

    @app.get("/api/studio/projects/{project_id}/music/{clip_id}/stream")
    async def api_studio_music_stream(project_id: int, clip_id: int) -> Response:
        _require_studio_project(project_id)
        clip = db.get_studio_music_clip(project_id, clip_id)
        if clip is None:
            raise HTTPException(status_code=404, detail="music_missing")
        path = Path(clip.file_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="music_missing")
        media_type = MIME_BY_SUFFIX.get(path.suffix.lower(), "application/octet-stream")
        return FileResponse(
            path,
            media_type=media_type,
            content_disposition_type="inline",
            headers={
                "Accept-Ranges": "bytes",
                "Cache-Control": "no-store",
            },
        )

    @app.patch("/api/studio/projects/{project_id}")
    async def api_studio_project_update(
        project_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict) or "title" not in payload:
            raise HTTPException(
                status_code=400, detail="JSON body must include title"
            )
        raw_title = payload.get("title")
        if not isinstance(raw_title, str):
            raise HTTPException(status_code=400, detail="title must be a string")
        try:
            project = db.set_studio_project_title(project_id, raw_title)
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        return JSONResponse(
            {
                "ok": True,
                "id": project.id,
                "title": project.title,
                "updated_at": project.updated_at,
            }
        )

    @app.post("/api/studio/projects")
    async def api_studio_project_create(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        raw_title = payload.get("title", "Your story")
        if raw_title is not None and not isinstance(raw_title, str):
            raise HTTPException(status_code=400, detail="title must be a string")
        project = db.create_studio_project(
            raw_title if isinstance(raw_title, str) else "Your story"
        )
        return JSONResponse(
            {
                "ok": True,
                "id": project.id,
                "title": project.title,
                "created_at": project.created_at,
                "updated_at": project.updated_at,
            },
            status_code=201,
        )

    @app.delete("/api/studio/projects/{project_id}")
    async def api_studio_project_delete(project_id: int) -> JSONResponse:
        """Delete a project and its clips. Never deletes media assets."""
        deleted = db.delete_studio_project(project_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="studio project not found")
        return JSONResponse({"ok": True, "deleted": True})

    @app.post("/api/studio/reorder")
    async def api_studio_reorder(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        raw_ids = payload.get("ordered_ids")
        if not isinstance(raw_ids, list) or not all(
            isinstance(x, int) and not isinstance(x, bool) for x in raw_ids
        ):
            raise HTTPException(
                status_code=400, detail="ordered_ids must be a list of integers"
            )
        open_project = db.resolve_studio_page_project()
        if open_project is None:
            raise HTTPException(status_code=400, detail="no studio project open")
        try:
            with story_edit(db, open_project.id, group=_history_group(request)):
                ordered = db.reorder_studio_items(
                    [int(x) for x in raw_ids], project_id=open_project.id
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        items = db.list_studio_items(open_project.id)
        summary = _studio_summary(open_project.id, items)
        return JSONResponse(
            {"ok": True, "ordered_ids": ordered, "summary": summary.as_dict()}
        )

    @app.post("/api/studio/title-cards")
    async def api_studio_add_title_card() -> JSONResponse:
        open_project = db.resolve_studio_page_project()
        if open_project is None:
            raise HTTPException(status_code=400, detail="no studio project open")
        try:
            clip = db.add_studio_title_card(
                open_project.id, title_text=open_project.title
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        items = db.list_studio_items(open_project.id)
        summary = _studio_summary(open_project.id, items)
        return JSONResponse(
            {
                "ok": True,
                "id": clip.id,
                "title": clip.title_text or "",
                "subtitle": clip.subtitle_text or "",
                "duration_s": clip.card_duration_s,
                "background": clip.background,
                "summary": summary.as_dict(),
            }
        )

    @app.patch("/api/studio/{studio_item_id}/title-card")
    async def api_studio_patch_title_card(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        kwargs: dict[str, Any] = {}
        if "title" in payload:
            if payload["title"] is not None and not isinstance(payload["title"], str):
                raise HTTPException(status_code=400, detail="title must be a string")
            kwargs["title_text"] = payload.get("title") or ""
        if "subtitle" in payload:
            if payload["subtitle"] is not None and not isinstance(
                payload["subtitle"], str
            ):
                raise HTTPException(status_code=400, detail="subtitle must be a string")
            kwargs["subtitle_text"] = payload.get("subtitle") or ""
        if "duration_s" in payload:
            raw = payload.get("duration_s")
            if not isinstance(raw, (int, float)) or isinstance(raw, bool):
                raise HTTPException(status_code=400, detail="duration_s must be a number")
            kwargs["card_duration_s"] = float(raw)
        if "background" in payload:
            if not isinstance(payload["background"], str):
                raise HTTPException(status_code=400, detail="background must be a string")
            kwargs["background"] = payload["background"]
        if not kwargs:
            raise HTTPException(status_code=400, detail="no title card fields to update")
        try:
            with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
                clip = db.update_studio_title_card(studio_item_id, **kwargs)
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        items = db.list_studio_items(clip.project_id)
        summary = _studio_summary(clip.project_id, items)
        lang = lang_from_request(request)
        primary, secondary = display_lines(clip.title_text, clip.subtitle_text, lang)
        return JSONResponse(
            {
                "ok": True,
                "id": clip.id,
                "title": clip.title_text or "",
                "subtitle": clip.subtitle_text or "",
                "duration_s": clip.card_duration_s,
                "background": clip.background,
                "display_title": primary,
                "display_subtitle": secondary,
                "summary": summary.as_dict(),
            }
        )

    @app.patch("/api/studio/{studio_item_id}/photo-duration")
    async def api_studio_photo_duration(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict) or "duration_s" not in payload:
            raise HTTPException(
                status_code=400, detail="JSON body must include duration_s"
            )
        raw = payload.get("duration_s")
        if raw is not None and not isinstance(raw, (int, float)):
            raise HTTPException(
                status_code=400, detail="duration_s must be a number or null"
            )
        duration_s: float | None = None if raw is None else float(raw)
        try:
            with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
                item = db.set_studio_photo_duration(studio_item_id, duration_s)
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        items = db.list_studio_items(item.project_id)
        summary = _studio_summary(item.project_id, items)
        seconds = effective_seconds(
            kind=item.kind or "unknown",
            photo_duration_s=item.photo_duration_s,
            duration_s=item.duration_s,
            available=item.available,
            source_in_s=item.source_in_s,
            source_out_s=item.source_out_s,
            playback_speed=item.playback_speed,
        )
        return JSONResponse(
            {
                "ok": True,
                "id": item.id,
                "photo_duration_s": item.photo_duration_s,
                "effective_duration_s": seconds,
                "summary": summary.as_dict(),
            }
        )

    @app.patch("/api/studio/{studio_item_id}/image")
    async def api_studio_image(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=400, detail="JSON body must include an image adjustment"
            )
        try:
            with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
                item = db.set_studio_image_adjust(studio_item_id, payload)
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        image = image_adjust_from_effect_settings(item.effect_settings)
        return JSONResponse(
            {
                "ok": True,
                "id": item.id,
                "image": image.as_dict(),
            }
        )

    async def _import_lut_from_request(request: Request) -> JSONResponse:
        """Shared import for ``/api/luts`` and the Studio alias."""
        content_type = (request.headers.get("content-type") or "").lower()
        try:
            if "multipart/form-data" in content_type:
                form = await request.form()
                upload = form.get("file")
                if upload is None or not hasattr(upload, "read"):
                    raise HTTPException(status_code=400, detail="LUT file is required")
                data = await upload.read()
                filename = getattr(upload, "filename", None) or "look.cube"
                result = import_lut_bytes(
                    db, settings.data_dir, data, source_label=str(filename)
                )
            else:
                payload = await request.json()
                if not isinstance(payload, dict):
                    raise HTTPException(
                        status_code=400, detail="JSON body must include a path"
                    )
                path_value = payload.get("path")
                if not isinstance(path_value, str) or not path_value.strip():
                    raise HTTPException(status_code=400, detail="LUT path is required")
                result = import_lut_path(db, settings.data_dir, Path(path_value))
        except LutInvalidError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail="LUT file could not be imported"
            ) from exc
        try:
            require_lut_asset(settings.data_dir, result.entry.asset_name)
        except LutMissingError as exc:
            raise HTTPException(status_code=500, detail="LUT storage failed") from exc
        return JSONResponse(result.as_dict())

    @app.get("/api/luts")
    async def api_luts_list() -> JSONResponse:
        entries = [entry.as_dict() for entry in list_catalog(db, settings.data_dir)]
        return JSONResponse({"ok": True, "luts": entries})

    @app.post("/api/luts")
    async def api_luts_import(request: Request) -> JSONResponse:
        return await _import_lut_from_request(request)

    @app.patch("/api/luts/{asset_name}")
    async def api_luts_rename(asset_name: str, request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=400, detail="JSON body must include display_name"
            )
        name = payload.get("display_name")
        if not isinstance(name, str):
            raise HTTPException(status_code=400, detail="display_name is required")
        try:
            entry = rename_lut(db, settings.data_dir, asset_name, name)
        except LutMissingError as exc:
            raise HTTPException(status_code=404, detail="LUT not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, **entry.as_dict()})

    @app.delete("/api/luts/{asset_name}")
    async def api_luts_delete(asset_name: str) -> JSONResponse:
        try:
            delete_lut(db, settings.data_dir, asset_name)
        except LutMissingError as exc:
            raise HTTPException(status_code=404, detail="LUT not found") from exc
        except LutInUseError as exc:
            return JSONResponse(
                {
                    "ok": False,
                    "in_use": True,
                    "clip_count": exc.usage.clip_count,
                    "project_count": exc.usage.project_count,
                    "project_titles": list(exc.usage.project_titles),
                    "detail": "LUT is in use",
                },
                status_code=409,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except LutInvalidError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True})

    @app.post("/api/luts/open-folder")
    async def api_luts_open_folder() -> JSONResponse:
        from orga_drone.desktop import (
            DesktopActionUnavailable,
            can_reveal_local_file,
            reveal_local_file,
        )

        if not can_reveal_local_file():
            return JSONResponse(
                {
                    "ok": False,
                    "status": "unavailable",
                    "detail": "Opening the LUT folder is not available on this platform.",
                },
                status_code=503,
            )
        folder = lut_asset_dir(settings.data_dir)
        try:
            # Reveal a file inside the folder when possible so Explorer opens here.
            sample = next((p for p in folder.iterdir() if p.is_file()), None)
            reveal_local_file(sample if sample is not None else folder)
        except DesktopActionUnavailable as exc:
            return JSONResponse(
                {"ok": False, "status": "unavailable", "detail": str(exc)},
                status_code=503,
            )
        except OSError as exc:
            raise HTTPException(
                status_code=400, detail="Could not open the LUT folder"
            ) from exc
        return JSONResponse({"ok": True, "path": str(folder)})

    @app.post("/api/studio/luts")
    async def api_studio_lut_import(request: Request) -> JSONResponse:
        """Thin alias for ``POST /api/luts`` (existing Studio clients)."""
        return await _import_lut_from_request(request)

    @app.patch("/api/studio/{studio_item_id}/detail")
    async def api_studio_detail(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=400, detail="JSON body must include sharpen or denoise"
            )
        try:
            with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
                item = db.set_studio_detail(studio_item_id, payload)
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        detail = detail_from_effect_settings(item.effect_settings)
        return JSONResponse(
            {"ok": True, "id": item.id, "detail": detail.as_dict()}
        )

    @app.patch("/api/studio/{studio_item_id}/look")
    async def api_studio_quick_look(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=400, detail="JSON body must include a quick look id"
            )
        try:
            with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
                item = db.set_studio_quick_look(studio_item_id, payload)
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        return JSONResponse(
            {
                "ok": True,
                "id": item.id,
                "quick_look": look_id_from_effect_settings(item.effect_settings),
                "image": image_adjust_from_effect_settings(item.effect_settings).as_dict(),
            }
        )

    @app.get("/api/studio/{studio_item_id}/preview-frame")
    async def api_studio_preview_frame(
        studio_item_id: int,
        t_s: float = Query(0.0),
        detail: int = Query(0),
    ) -> Response:
        """JPEG still using the same grade+LUT builders as export (ADR 0028).

        ``t_s`` is the source offset from the clip in-point (after slow-motion /
        speed mapping on the client), not Story time.
        """
        project_id = _clip_project_id(studio_item_id)
        if project_id is None:
            raise HTTPException(status_code=404, detail="Studio item not found")
        clip = next(
            (item for item in db.list_studio_items(project_id) if item.id == studio_item_id),
            None,
        )
        if clip is None:
            raise HTTPException(status_code=404, detail="Studio item not found")
        if clip.item_kind != "media" or clip.kind not in {"photo", "video"}:
            raise HTTPException(
                status_code=422,
                detail="Preview stills are only for photo and video clips.",
            )
        if not clip.media_path or not clip.available:
            raise HTTPException(status_code=409, detail="This media file is offline.")
        media_path = Path(clip.media_path)
        if not media_path.is_file():
            raise HTTPException(status_code=409, detail="This media file is missing.")
        local = quantize_preview_time(float(t_s) if t_s == t_s else 0.0)
        from orga_drone.studio_color_animation import (
            apply_keyed_look,
            color_animation_from_effect_settings,
            image_adjust_at,
        )

        base_look = color_look_from_effect_settings(clip.effect_settings)
        anim = color_animation_from_effect_settings(clip.effect_settings)
        if clip.kind == "video":
            image = image_adjust_at(clip.effect_settings, local)
            look = apply_keyed_look(base_look, anim, local)
        else:
            image = image_adjust_from_effect_settings(clip.effect_settings)
            look = base_look
        if not look_needs_preview_still(look):
            raise HTTPException(
                status_code=422,
                detail="No color file is active on this clip.",
            )
        origin = float(clip.source_start or 0.0)
        abs_t = origin + local
        if clip.source_end is not None:
            abs_t = min(abs_t, float(clip.source_end))
        abs_t = max(0.0, abs_t)
        try:
            jpeg = await asyncio.to_thread(
                render_preview_frame,
                PreviewFrameRequest(
                    media_path=media_path,
                    kind=str(clip.kind),
                    source_time_s=abs_t if clip.kind == "video" else 0.0,
                    image=image,
                    look=look,
                    detail=bool(detail),
                ),
                data_dir=settings.data_dir,
            )
        except LutMissingError as exc:
            raise HTTPException(
                status_code=409,
                detail="A LUT file is missing. Choose the .cube again in Image, or clear the look.",
            ) from exc
        except PreviewFrameError as exc:
            status = 409 if exc.code in {"media_missing", "lut_invalid"} else 500
            if exc.code == "unsupported":
                status = 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        return FileResponse(
            jpeg,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "private, max-age=60",
                "X-Orga-Preview-Still": "1",
            },
        )

    @app.patch("/api/studio/{studio_item_id}/color")
    async def api_studio_color_look(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=400, detail="JSON body must include a color look"
            )
        conversion = payload.get("conversion_lut")
        creative = payload.get("creative_lut")
        for name in (conversion, creative):
            if isinstance(name, str) and name:
                try:
                    require_lut_asset(settings.data_dir, name)
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                except LutMissingError as exc:
                    raise HTTPException(
                        status_code=400,
                        detail="A LUT file is missing. Choose the .cube again.",
                    ) from exc
        try:
            with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
                item = db.set_studio_color_look(studio_item_id, payload)
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        look = color_look_from_effect_settings(item.effect_settings)
        return JSONResponse(
            {
                "ok": True,
                "id": item.id,
                "color_look": look.as_dict(),
            }
        )

    @app.patch("/api/studio/{studio_item_id}/color-animation")
    async def api_studio_color_animation(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=400, detail="JSON body must include a color animation"
            )
        try:
            with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
                item = db.set_studio_color_animation(studio_item_id, payload)
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        anim = color_animation_from_effect_settings(item.effect_settings)
        return JSONResponse(
            {
                "ok": True,
                "id": item.id,
                "color_animation": anim.as_dict() if anim.keys or anim.is_active else None,
                "effect_lane": stored_lane(item.effect_settings),
            }
        )

    @app.patch("/api/studio/{studio_item_id}/saturation-ramp")
    async def api_studio_saturation_ramp(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=400, detail="JSON body must include a saturation ramp"
            )
        try:
            with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
                item = db.set_studio_saturation_ramp(studio_item_id, payload)
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        ramp = saturation_ramp_from_effect_settings(item.effect_settings)
        return JSONResponse(
            {
                "ok": True,
                "id": item.id,
                "saturation_ramp": ramp.as_dict(),
            }
        )

    @app.patch("/api/studio/{studio_item_id}/effect-lane")
    async def api_studio_effect_lane(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="JSON body must include an effect bar")
        try:
            with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
                item = db.update_effect_lane(studio_item_id, payload)
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        from orga_drone.studio_effect_lane import stored_lane

        stored = stored_lane(item.effect_settings)
        seconds = effective_seconds(
            kind=item.kind or "video",
            photo_duration_s=item.photo_duration_s,
            duration_s=item.duration_s,
            available=item.available,
            source_in_s=item.source_start,
            source_out_s=item.source_end,
            playback_speed=item.playback_speed,
            effect_settings=item.effect_settings,
        )
        zoom = stored.get("zoom_bar")
        slow = stored.get("slow_bar")
        return JSONResponse(
            {
                "ok": True,
                "id": item.id,
                "playback_speed": item.playback_speed,
                "effective_duration_s": seconds,
                "frame": frame_from_effect_settings(item.effect_settings).as_dict(),
                "masks": [
                    mask.as_dict() for mask in masks_from_effect_settings(item.effect_settings)
                ],
                "zoom_bar": zoom if isinstance(zoom, dict) else None,
                "slow_bar": slow if isinstance(slow, dict) else None,
                "effect_lane": stored,
            }
        )

    @app.patch("/api/studio/{studio_item_id}/clip-audio")
    async def api_studio_clip_audio(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="JSON body must include an audio range")
        try:
            with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
                item = db.set_studio_clip_audio(studio_item_id, payload)
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        audio = detached_audio_from_effect_settings(item.effect_settings)
        return JSONResponse(
            {
                "ok": True,
                "id": item.id,
                "source_in_s": item.source_start,
                "source_out_s": item.source_end,
                "audio": audio.as_dict(),
            }
        )

    @app.patch("/api/studio/{studio_item_id}/overlays")
    async def api_studio_overlays(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="JSON body must include overlays")
        try:
            with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
                item, clamped = db.set_studio_overlays(studio_item_id, payload)
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        seconds = effective_seconds(
            kind=item.kind or "photo",
            photo_duration_s=item.photo_duration_s,
            duration_s=item.duration_s,
            available=item.available,
            source_in_s=item.source_start,
            source_out_s=item.source_end,
            card_duration_s=item.card_duration_s,
            playback_speed=item.playback_speed,
        )
        overlays = overlays_from_effect_settings(
            item.effect_settings,
            duration_s=float(seconds or DEFAULT_PHOTO_DURATION_S),
        )
        return JSONResponse(
            {
                "ok": True,
                "id": item.id,
                "clamped": clamped,
                "overlays": [entry.as_dict() for entry in overlays],
            }
        )

    @app.post("/api/studio/overlay-assets")
    async def api_studio_overlay_asset(request: Request) -> JSONResponse:
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(status_code=400, detail="overlay image must be a PNG or JPEG")
        data = await upload.read()
        try:
            asset_name = store_overlay_asset(settings.data_dir, data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "asset_name": asset_name})

    @app.get("/studio/overlay-assets/{asset_name}")
    def studio_overlay_asset(asset_name: str) -> FileResponse:
        try:
            path = resolve_overlay_asset(settings.data_dir, asset_name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Overlay image is missing.") from exc
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Overlay image is missing.")
        media_type = "image/png" if path.suffix == ".png" else "image/jpeg"
        return FileResponse(path, media_type=media_type)

    @app.patch("/api/studio/{studio_item_id}/masks")
    async def api_studio_masks(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="JSON body must include masks")
        try:
            with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
                item = db.set_studio_masks(studio_item_id, payload)
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        masks = masks_from_effect_settings(item.effect_settings)
        return JSONResponse(
            {
                "ok": True,
                "id": item.id,
                "masks": [mask.as_dict() for mask in masks],
            }
        )

    @app.patch("/api/studio/{studio_item_id}/frame")
    async def api_studio_frame(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=400, detail="JSON body must include frame"
            )
        try:
            with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
                item = db.set_studio_frame(studio_item_id, payload)
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        frame = frame_from_effect_settings(item.effect_settings)
        return JSONResponse(
            {
                "ok": True,
                "id": item.id,
                "frame": frame.as_dict(),
            }
        )

    @app.get("/map-tiles/{z}/{x}/{y}.png")
    async def map_tile(z: int, x: int, y: int) -> FileResponse:
        """One cached OpenStreetMap tile for the Studio flight-map panel."""
        path = cached_osm_tile(z, x, y)
        if path is None:
            raise HTTPException(status_code=404, detail="Map tile is not available")
        return FileResponse(path, media_type="image/png")

    @app.patch("/api/studio/{studio_item_id}/map")
    async def api_studio_map(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="JSON body must include map")
        try:
            item = db.set_studio_map(studio_item_id, payload)
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        placement = map_from_effect_settings(item.effect_settings)
        return JSONResponse(
            {
                "ok": True,
                "id": item.id,
                "map": placement.as_dict(),
            }
        )

    @app.patch("/api/studio/{studio_item_id}/hud")
    async def api_studio_hud(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        from orga_drone.studio_hud import hud_enabled_from_effect_settings

        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=400, detail="JSON body must include enabled"
            )
        try:
            item = db.set_studio_hud(studio_item_id, payload)
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        return JSONResponse(
            {
                "ok": True,
                "id": item.id,
                "enabled": hud_enabled_from_effect_settings(item.effect_settings),
            }
        )


    @app.patch("/api/studio/{studio_item_id}/section")
    async def api_studio_section(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict) or not all(
            key in payload for key in ("source_in_s", "source_out_s", "repeats")
        ):
            raise HTTPException(
                status_code=400,
                detail="JSON body must include source_in_s, source_out_s, and repeats",
            )
        raw_in = payload.get("source_in_s")
        raw_out = payload.get("source_out_s")
        raw_repeats = payload.get("repeats")
        if isinstance(raw_in, bool) or not isinstance(raw_in, (int, float)):
            raise HTTPException(status_code=400, detail="source in must be a number")
        if isinstance(raw_out, bool) or not isinstance(raw_out, (int, float)):
            raise HTTPException(status_code=400, detail="source out must be a number")
        if isinstance(raw_repeats, bool) or not isinstance(raw_repeats, (int, float)):
            raise HTTPException(
                status_code=400, detail="repeat count must be a whole number from 1 to 8"
            )
        try:
            with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
                item = db.set_studio_section(
                    studio_item_id,
                    source_in_s=float(raw_in),
                    source_out_s=float(raw_out),
                    repeats=raw_repeats,
                )
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        items = db.list_studio_items(item.project_id)
        summary = _studio_summary(item.project_id, items)
        repeats = section_repeats_from_effect_settings(item.effect_settings)
        seconds = effective_item_seconds(
            item,
            items,
            soundtrack_once_s(db.list_studio_music(item.project_id)),
        )
        return JSONResponse(
            {
                "ok": True,
                "id": item.id,
                "source_in_s": item.source_in_s,
                "source_out_s": item.source_out_s,
                "section_repeats": repeats,
                "effective_duration_s": seconds,
                "summary": summary.as_dict(),
            }
        )

    @app.patch("/api/studio/{studio_item_id}/forward-loop")
    async def api_studio_forward_loop(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict) or "enabled" not in payload:
            raise HTTPException(status_code=400, detail="JSON body must include enabled")
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            raise HTTPException(status_code=400, detail="enabled must be true or false")
        transition: str | None = None
        if "transition" in payload:
            raw_transition = payload.get("transition")
            if raw_transition not in {"off", "crossfade"}:
                raise HTTPException(
                    status_code=400, detail="transition must be off or crossfade"
                )
            transition = str(raw_transition)
        transition_s: float | None = None
        if "duration_s" in payload and payload.get("duration_s") is not None:
            raw_duration = payload.get("duration_s")
            if isinstance(raw_duration, bool) or not isinstance(raw_duration, (int, float)):
                raise HTTPException(status_code=400, detail="duration_s must be a number")
            transition_s = float(raw_duration)
        try:
            with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
                item = db.set_studio_forward_loop(
                    studio_item_id,
                    enabled,
                    transition=transition,
                    transition_s=transition_s,
                )
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        items = db.list_studio_items(item.project_id)
        once = soundtrack_once_s(db.list_studio_music(item.project_id))
        resolution = resolve_forward_loop(items, once)
        summary = summarize_studio_items(items, soundtrack_once_s=once)
        seconds = effective_item_seconds(item, items, once)
        active = bool(
            resolution.active and resolution.item_id == item.id
        )
        view = clip_forward_loop_view(item, resolution, once)
        return JSONResponse(
            {
                "ok": True,
                "id": item.id,
                "enabled": bool(view["requested"]),
                "active": active,
                "reason": view["reason"],
                "effective_duration_s": seconds,
                "section_repeats": section_repeats_from_effect_settings(
                    item.effect_settings
                ),
                "transition": view["transition"],
                "transition_s": view["transition_s"],
                "overlap_s": view["overlap_s"],
                "plays": view["plays"],
                "partial_s": view["partial_s"],
                "clamped": view["clamped"],
                "summary": summary.as_dict(),
            }
        )

    @app.patch("/api/studio/{studio_item_id}/loop-effect")
    async def api_studio_loop_effect(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict) or "transition" not in payload:
            raise HTTPException(status_code=400, detail="JSON body must include transition")
        raw_transition = payload.get("transition")
        if raw_transition not in {"off", "crossfade", "cinematic", "match"}:
            raise HTTPException(
                status_code=400,
                detail="transition must be off, crossfade, cinematic, or match",
            )
        transition_s: float | None = None
        if "duration_s" in payload and payload.get("duration_s") is not None:
            raw_duration = payload.get("duration_s")
            if isinstance(raw_duration, bool) or not isinstance(raw_duration, (int, float)):
                raise HTTPException(status_code=400, detail="duration_s must be a number")
            transition_s = float(raw_duration)
        curve: str | None = None
        if payload.get("curve") is not None:
            raw_curve = payload.get("curve")
            if raw_curve not in {"linear", "smooth"}:
                raise HTTPException(status_code=400, detail="curve must be linear or smooth")
            curve = str(raw_curve)
        try:
            with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
                item = db.set_studio_loop_effect(
                    studio_item_id,
                    transition=str(raw_transition),
                    duration_s=transition_s,
                    curve=curve,
                )
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        items = db.list_studio_items(item.project_id)
        once = soundtrack_once_s(db.list_studio_music(item.project_id))
        resolution = resolve_forward_loop(items, once)
        summary = summarize_studio_items(items, soundtrack_once_s=once)
        seconds = effective_item_seconds(item, items, once)
        view = clip_forward_loop_view(item, resolution, once)
        return JSONResponse(
            {
                "ok": True,
                "id": item.id,
                "effective_duration_s": seconds,
                "section_repeats": section_repeats_from_effect_settings(item.effect_settings),
                "transition": view["transition"],
                "transition_s": view["transition_s"],
                "overlap_s": view["overlap_s"],
                "plays": view["plays"],
                "partial_s": view["partial_s"],
                "clamped": view["clamped"],
                "match_state": view["match_state"],
                "match_in_s": view["match_in_s"],
                "match_out_s": view["match_out_s"],
                "curve": view["curve"],
                "summary": summary.as_dict(),
            }
        )

    @app.patch("/api/studio/{studio_item_id}/transition")
    async def api_studio_transition(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict) or "type" not in payload:
            raise HTTPException(status_code=400, detail="JSON body must include type")
        raw_type = payload.get("type")
        if raw_type is not None and not isinstance(raw_type, str):
            raise HTTPException(status_code=400, detail="type must be a string")
        raw_dur = payload.get("duration_s", None)
        if "duration_s" in payload and raw_dur is not None and not isinstance(
            raw_dur, (int, float)
        ):
            raise HTTPException(
                status_code=400, detail="duration_s must be a number or null"
            )
        duration_s: float | None
        if "duration_s" not in payload:
            duration_s = None
        else:
            duration_s = None if raw_dur is None else float(raw_dur)
        try:
            with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
                item = db.set_studio_transition(
                    studio_item_id, raw_type, duration_s
                )
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        items = db.list_studio_items(item.project_id)
        summary = _studio_summary(item.project_id, items)
        _durs, applied_list, source_indexes = apply_for_items(items)
        applied = None
        for seq_i, item_idx in enumerate(source_indexes):
            if items[item_idx].id == item.id and seq_i < len(applied_list):
                applied = applied_list[seq_i]
                break
        return JSONResponse(
            {
                "ok": True,
                "id": item.id,
                "type": normalize_type(item.transition),
                "duration_s": item.transition_duration_s,
                "applied_type": applied.type if applied is not None else "cut",
                "applied_duration_s": applied.duration_s if applied is not None else 0.0,
                "fallback_cut": bool(applied.fallback_cut) if applied is not None else False,
                "clamped": bool(applied.clamped) if applied is not None else False,
                "summary": summary.as_dict(),
            }
        )

    @app.post("/api/studio/{studio_item_id}/speed")
    async def api_studio_speed(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict) or "speed" not in payload:
            raise HTTPException(status_code=400, detail="JSON body must include speed")
        raw_speed = payload.get("speed")
        if isinstance(raw_speed, bool) or not isinstance(raw_speed, (int, float)):
            raise HTTPException(status_code=400, detail="speed must be 1, 0.5, or 0.25")
        has_in = "range_in_s" in payload and payload.get("range_in_s") is not None
        has_out = "range_out_s" in payload and payload.get("range_out_s") is not None
        if has_in != has_out:
            raise HTTPException(
                status_code=400, detail="speed range needs both start and end"
            )
        range_in: float | None = None
        range_out: float | None = None
        if has_in and has_out:
            raw_in = payload.get("range_in_s")
            raw_out = payload.get("range_out_s")
            if isinstance(raw_in, bool) or not isinstance(raw_in, (int, float)):
                raise HTTPException(status_code=400, detail="range_in_s must be a number")
            if isinstance(raw_out, bool) or not isinstance(raw_out, (int, float)):
                raise HTTPException(status_code=400, detail="range_out_s must be a number")
            range_in = float(raw_in)
            range_out = float(raw_out)
        try:
            with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
                changed, selected_id = db.set_studio_playback_speed(
                    studio_item_id,
                    float(raw_speed),
                    range_in_s=range_in,
                    range_out_s=range_out,
                )
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        items = db.list_studio_items(changed[0].project_id)
        summary = _studio_summary(changed[0].project_id, items)

        def _speed_row(clip: Any) -> dict[str, Any]:
            return {
                "id": clip.id,
                "source_in_s": clip.source_in_s,
                "source_out_s": clip.source_out_s,
                "playback_speed": clip.playback_speed,
                "effective_duration_s": effective_seconds(
                    kind=clip.kind or "unknown",
                    photo_duration_s=clip.photo_duration_s,
                    duration_s=clip.duration_s,
                    available=clip.available,
                    source_in_s=clip.source_in_s,
                    source_out_s=clip.source_out_s,
                    playback_speed=clip.playback_speed,
                ),
            }

        return JSONResponse(
            {
                "ok": True,
                "selected_id": selected_id,
                "clips": [_speed_row(clip) for clip in changed],
                "summary": summary.as_dict(),
            }
        )

    @app.post("/api/studio/{studio_item_id}/cut")
    async def api_studio_cut(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict) or "local_s" not in payload:
            raise HTTPException(
                status_code=400, detail="JSON body must include local_s"
            )
        raw = payload.get("local_s")
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            raise HTTPException(status_code=400, detail="local_s must be a number")
        try:
            with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
                left, right = db.cut_studio_video_item(studio_item_id, float(raw))
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        items = db.list_studio_items(left.project_id)
        summary = _studio_summary(left.project_id, items)
        return JSONResponse(
            {
                "ok": True,
                "left_id": left.id,
                "right_id": right.id,
                "left": {
                    "id": left.id,
                    "source_in_s": left.source_in_s,
                    "source_out_s": left.source_out_s,
                    "effective_duration_s": effective_seconds(
                        kind=left.kind or "unknown",
                        photo_duration_s=left.photo_duration_s,
                        duration_s=left.duration_s,
                        available=left.available,
                        source_in_s=left.source_in_s,
                        source_out_s=left.source_out_s,
                        playback_speed=left.playback_speed,
                        section_repeats=section_repeats_from_effect_settings(
                            left.effect_settings
                        ),
                    ),
                },
                "right": {
                    "id": right.id,
                    "source_in_s": right.source_in_s,
                    "source_out_s": right.source_out_s,
                    "effective_duration_s": effective_seconds(
                        kind=right.kind or "unknown",
                        photo_duration_s=right.photo_duration_s,
                        duration_s=right.duration_s,
                        available=right.available,
                        source_in_s=right.source_in_s,
                        source_out_s=right.source_out_s,
                        playback_speed=right.playback_speed,
                        section_repeats=section_repeats_from_effect_settings(
                            right.effect_settings
                        ),
                    ),
                },
                "summary": summary.as_dict(),
            }
        )

    def _merge_reason(request: Request, code: str) -> str:
        translate = get_translator(lang_from_request(request))
        return translate(MERGE_REASONS.get(code, MERGE_REASONS["settings"]))

    @app.get("/api/studio/{studio_item_id}/merge-previous")
    async def api_studio_merge_previous_status(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        project_id = _clip_project_id(studio_item_id)
        if project_id is None:
            raise HTTPException(status_code=404, detail=_merge_reason(request, "not_found"))
        try:
            from orga_drone.studio_merge import plan_merge

            plan_merge(db.list_studio_items(project_id), studio_item_id)
        except MergeBlocked as exc:
            return JSONResponse(
                {"ok": False, "reason": _merge_reason(request, exc.code)}
            )
        return JSONResponse({"ok": True, "reason": ""})

    @app.post("/api/studio/{studio_item_id}/merge-previous")
    async def api_studio_merge_previous(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            with story_edit(
                db, _clip_project_id(studio_item_id), group=_history_group(request)
            ):
                merged = db.merge_studio_with_previous(studio_item_id)
        except MergeBlocked as exc:
            status = 404 if exc.code == "not_found" else 400
            raise HTTPException(
                status_code=status, detail=_merge_reason(request, exc.code)
            ) from exc
        return JSONResponse(
            {
                "ok": True,
                "id": merged.id,
                "source_in_s": merged.source_in_s,
                "source_out_s": merged.source_out_s,
                "effective_duration_s": effective_seconds(
                    kind=merged.kind or "unknown",
                    photo_duration_s=merged.photo_duration_s,
                    duration_s=merged.duration_s,
                    available=merged.available,
                    source_in_s=merged.source_in_s,
                    source_out_s=merged.source_out_s,
                    playback_speed=merged.playback_speed,
                    section_repeats=section_repeats_from_effect_settings(
                        merged.effect_settings
                    ),
                ),
            }
        )

    def _reuse_reason(request: Request, code: str) -> str:
        translate = get_translator(lang_from_request(request))
        return translate(REUSE_REASONS.get(code, REUSE_REASONS["outside"]))

    @app.post("/api/studio/{studio_item_id}/reuse-source")
    async def api_studio_reuse_source(
        studio_item_id: int,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail=_reuse_reason(request, "outside"))
        try:
            with story_edit(db, _clip_project_id(studio_item_id)):
                created = db.reuse_studio_source(
                    studio_item_id,
                    payload.get("source_in_s"),
                    payload.get("source_out_s"),
                )
        except ReuseBlocked as exc:
            status = 404 if exc.code == "not_found" else 400
            raise HTTPException(
                status_code=status, detail=_reuse_reason(request, exc.code)
            ) from exc
        return JSONResponse(
            {
                "ok": True,
                "id": created.id,
                "source_in_s": created.source_in_s,
                "source_out_s": created.source_out_s,
                "effective_duration_s": effective_seconds(
                    kind=created.kind or "unknown",
                    photo_duration_s=created.photo_duration_s,
                    duration_s=created.duration_s,
                    available=created.available,
                    source_in_s=created.source_in_s,
                    source_out_s=created.source_out_s,
                    playback_speed=created.playback_speed,
                    section_repeats=section_repeats_from_effect_settings(
                        created.effect_settings
                    ),
                ),
            }
        )

    @app.post("/api/studio/media/{media_id}/reuse-source")
    async def api_studio_original_scene(
        media_id: int,
        request: Request,
    ) -> JSONResponse:
        project = db.resolve_studio_page_project()
        if project is None:
            raise HTTPException(status_code=404, detail=_reuse_reason(request, "not_found"))
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail=_reuse_reason(request, "outside"))
        before_id = payload.get("before_id")
        if before_id is not None and (
            isinstance(before_id, bool) or not isinstance(before_id, int)
        ):
            raise HTTPException(status_code=400, detail=_reuse_reason(request, "outside"))
        try:
            with story_edit(db, project.id):
                created = db.insert_studio_original_scene(
                    project.id,
                    media_id,
                    payload.get("source_in_s"),
                    payload.get("source_out_s"),
                    before_id=before_id,
                )
        except ReuseBlocked as exc:
            status = 404 if exc.code == "not_found" else 400
            raise HTTPException(
                status_code=status, detail=_reuse_reason(request, exc.code)
            ) from exc
        return JSONResponse(
            {
                "ok": True,
                "id": created.id,
                "source_in_s": created.source_in_s,
                "source_out_s": created.source_out_s,
                "effective_duration_s": effective_seconds(
                    kind=created.kind or "unknown",
                    photo_duration_s=created.photo_duration_s,
                    duration_s=created.duration_s,
                    available=created.available,
                    source_in_s=created.source_in_s,
                    source_out_s=created.source_out_s,
                    playback_speed=created.playback_speed,
                    section_repeats=section_repeats_from_effect_settings(
                        created.effect_settings
                    ),
                ),
            }
        )

    @app.get("/api/studio/export/options")
    async def api_studio_export_options(
        project_id: int | None = None,
    ) -> JSONResponse:
        from orga_drone.studio_export import build_export_options_payload

        try:
            payload = await asyncio.to_thread(build_export_options_payload, db, project_id)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, **payload})

    @app.post("/api/studio/export")
    async def api_studio_export(request: Request) -> JSONResponse:
        from orga_drone.export.studio_encoder import StudioExportError
        from orga_drone.studio_export import prepare_studio_export, run_studio_export

        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        height = payload.get("height")
        output_path = payload.get("output_path")
        overwrite = bool(payload.get("overwrite"))
        project_id = payload.get("project_id")
        quality = payload.get("quality")
        if not isinstance(height, int) or isinstance(height, bool):
            raise HTTPException(status_code=400, detail="height must be an integer")
        if not isinstance(output_path, str) or not output_path.strip():
            raise HTTPException(status_code=400, detail="output_path is required")
        if project_id is not None and (
            not isinstance(project_id, int) or isinstance(project_id, bool)
        ):
            raise HTTPException(status_code=400, detail="project_id must be an integer")

        translate = get_translator(lang_from_request(request))
        # Pre-flight validation before creating a job. ``overwrite`` is ignored.
        try:
            await asyncio.to_thread(
                prepare_studio_export,
                db,
                height=height,
                output_path=Path(output_path),
                overwrite=overwrite,
                project_id=project_id,
                quality=quality,
            )
        except StudioExportError as exc:
            msg = translate(str(exc))
            status = 409 if "already exists" in str(exc).lower() else 400
            raise HTTPException(status_code=status, detail=msg) from exc

        def _work(
            on_progress: Callable[..., None],
            cancel_event: threading.Event | None,
        ) -> Path:
            return run_studio_export(
                db,
                height=height,
                output_path=Path(output_path),
                overwrite=overwrite,
                project_id=project_id,
                quality=quality,
                on_progress=on_progress,
                cancel_event=cancel_event,
            )

        return _begin_export_job(_work, translate)

    def _begin_export_job(
        work: Callable[..., Path],
        translate: Callable[[str], str],
    ) -> JSONResponse:
        from orga_drone.export.studio_encoder import ExportCancelled, StudioExportError

        store: ExportJobStore = app.state.export_jobs
        job = store.try_create()
        if job is None:
            raise HTTPException(
                status_code=409,
                detail="An export is already running. Wait for it to finish.",
            )
        cancel_event = store.cancel_event(job.id)

        def _worker() -> None:
            store.mark_running(job.id)

            def on_progress(progress: dict[str, Any]) -> None:
                store.apply_progress(job.id, progress)

            try:
                result = work(on_progress, cancel_event)
                store.complete(
                    job.id,
                    output_path=str(result),
                    directory=str(result.parent),
                )
            except ExportCancelled:
                store.finish_cancelled(job.id)
            except StudioExportError as exc:
                if cancel_event is not None and cancel_event.is_set():
                    store.finish_cancelled(job.id)
                else:
                    store.fail(job.id, translate(str(exc)))
            except Exception as exc:  # noqa: BLE001
                if cancel_event is not None and cancel_event.is_set():
                    store.finish_cancelled(job.id)
                else:
                    store.fail(job.id, f"Export failed: {exc}")

        threading.Thread(target=_worker, name=f"studio-export-{job.id}", daemon=True).start()
        return JSONResponse({"ok": True, "job_id": job.id})

    def _media_export_error(exc: BaseException, translate: Callable[[str], str]) -> HTTPException:
        from orga_drone.export.studio_encoder import StudioExportError

        if not isinstance(exc, StudioExportError):
            return HTTPException(status_code=400, detail=translate(str(exc)))
        status = 404 if str(exc) == "Media not found." else 400
        return HTTPException(status_code=status, detail=translate(str(exc)))

    @app.get("/api/media/{media_id}/export/options")
    async def api_media_export_options(request: Request, media_id: int) -> JSONResponse:
        from orga_drone.export.studio_encoder import StudioExportError
        from orga_drone.studio_export import build_media_export_options_payload

        translate = get_translator(lang_from_request(request))
        try:
            payload = await asyncio.to_thread(
                build_media_export_options_payload, db, media_id
            )
        except StudioExportError as exc:
            raise _media_export_error(exc, translate) from exc
        return JSONResponse({"ok": True, **payload})

    @app.post("/api/media/{media_id}/image-adjust")
    async def api_media_image_adjust(media_id: int, request: Request) -> JSONResponse:
        from orga_drone.db import make_identity_key

        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        translate = get_translator(lang_from_request(request))
        row = db.get_media(media_id)
        if row is None:
            raise HTTPException(status_code=404, detail=translate("Media not found."))
        if row.kind != "photo":
            raise HTTPException(
                status_code=400,
                detail=translate("Photo adjustments are only for a photo."),
            )
        from orga_drone.studio_looks import look_image_adjust, parse_look_payload

        try:
            look_id = parse_look_payload(payload)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=translate("Unknown look."),
            ) from exc
        try:
            if look_id and not export_payload_sets_adjust(payload):
                image = look_image_adjust(look_id)
            else:
                image = image_adjust_from_export_payload(payload)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=translate(
                    "Brightness, contrast, saturation, warmth, and fine-tune "
                    "sliders must be from -100 to 100."
                ),
            ) from exc
        if not export_payload_sets_adjust(payload) and not look_id:
            image = image_adjust_from_export_payload({"exposure": 0})
            look_id = ""
        # Moving a slider without look_id clears the named look (Custom).
        if "look_id" not in payload and "id" not in payload and export_payload_sets_adjust(
            payload
        ):
            look_id = ""
        db.set_image_adjust(
            row.path,
            image,
            identity_key=make_identity_key(row.filename, row.size_bytes, row.recorded_at),
            look_id=look_id,
        )
        return JSONResponse(
            {"ok": True, "image": image.as_dict(), "look_id": look_id or ""}
        )

    @app.post("/api/media/{media_id}/export")
    async def api_media_export(media_id: int, request: Request) -> JSONResponse:
        from orga_drone.export.studio_encoder import StudioExportError
        from orga_drone.studio_export import prepare_media_export, run_media_export

        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        preset = payload.get("preset")
        output_path = payload.get("output_path")
        overwrite = bool(payload.get("overwrite"))
        if not isinstance(preset, str) or not preset.strip():
            raise HTTPException(status_code=400, detail="preset is required")
        if not isinstance(output_path, str) or not output_path.strip():
            raise HTTPException(status_code=400, detail="output_path is required")
        translate = get_translator(lang_from_request(request))
        row = db.get_media(media_id)
        image = None
        still_format = None
        if row is not None and row.kind == "photo":
            from orga_drone.export.still_export import normalize_still_format

            try:
                if export_payload_sets_adjust(payload):
                    image = image_adjust_from_export_payload(payload)
                still_format = normalize_still_format(payload.get("still_format"))
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=translate(
                        "Brightness, contrast, saturation, and warmth must be from -100 to 100."
                    ),
                ) from exc
            except StudioExportError as exc:
                raise _media_export_error(exc, translate) from exc
        try:
            await asyncio.to_thread(
                prepare_media_export,
                db,
                media_id,
                preset=preset,
                output_path=Path(output_path),
                overwrite=overwrite,
                image=image,
                still_format=still_format,
            )
        except StudioExportError as exc:
            raise _media_export_error(exc, translate) from exc

        def _work(
            on_progress: Callable[..., None],
            cancel_event: threading.Event | None,
        ) -> Path:
            return run_media_export(
                db,
                media_id,
                preset=preset,
                output_path=Path(output_path),
                overwrite=overwrite,
                on_progress=on_progress,
                cancel_event=cancel_event,
                image=image,
                still_format=still_format,
            )

        return _begin_export_job(_work, translate)

    def _export_action_flags() -> dict[str, bool]:
        from orga_drone.desktop import can_open_local_file, can_reveal_local_file

        return {
            "open_available": can_open_local_file(),
            "reveal_available": can_reveal_local_file(),
        }

    def _studio_export_open_or_reveal(action: str) -> JSONResponse:
        from orga_drone.desktop import (
            DesktopActionUnavailable,
            can_open_local_file,
            can_reveal_local_file,
            open_local_file,
            reveal_local_file,
        )

        unavailable_error = (
            "open_unavailable" if action == "open" else "reveal_unavailable"
        )
        available = can_open_local_file() if action == "open" else can_reveal_local_file()
        if not available:
            return JSONResponse(
                {"status": "unavailable", "error": unavailable_error},
                status_code=503,
            )

        store: ExportJobStore = app.state.export_jobs
        last = store.get_last_success()
        if last is None:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "missing_file",
                    "detail": "No completed export is available.",
                },
                status_code=404,
            )
        path = Path(last.output_path)
        open_suffixes = {
            ".mp4",
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
            ".gif",
            ".heic",
            ".heif",
            ".tif",
            ".tiff",
            ".bmp",
            ".dng",
        }
        if (
            not path.is_absolute()
            or path.suffix.lower() not in open_suffixes
            or not path.is_file()
        ):
            return JSONResponse(
                {
                    "ok": False,
                    "error": "missing_file",
                    "detail": "The exported file is no longer available.",
                },
                status_code=404,
            )
        try:
            if action == "open":
                open_local_file(path)
            else:
                reveal_local_file(path)
        except DesktopActionUnavailable:
            return JSONResponse(
                {"status": "unavailable", "error": unavailable_error},
                status_code=503,
            )
        except OSError as exc:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "missing_file",
                    "detail": str(exc) or "The exported file is no longer available.",
                },
                status_code=404,
            )
        return JSONResponse(
            {"ok": True, "action": action, "filename": last.filename}
        )

    @app.post("/api/studio/export/jobs/{job_id}/cancel")
    async def api_studio_export_cancel(job_id: str) -> JSONResponse:
        from orga_drone.export.studio_encoder import cancel_export_process

        store: ExportJobStore = app.state.export_jobs
        event = store.request_cancel(job_id)
        if event is None:
            job = store.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Export job not found")
            return JSONResponse({"ok": True, "state": job.state})
        await asyncio.to_thread(cancel_export_process, event)
        return JSONResponse({"ok": True, "state": "cancelling"})

    @app.get("/api/studio/export/jobs/{job_id}")
    async def api_studio_export_job(job_id: str) -> JSONResponse:
        store: ExportJobStore = app.state.export_jobs
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Export job not found")
        return JSONResponse({"ok": True, **job.to_dict(), **_export_action_flags()})

    @app.post("/api/studio/export/open")
    async def api_studio_export_open() -> JSONResponse:
        return await asyncio.to_thread(_studio_export_open_or_reveal, "open")

    @app.post("/api/studio/export/reveal")
    async def api_studio_export_reveal() -> JSONResponse:
        return await asyncio.to_thread(_studio_export_open_or_reveal, "reveal")

    @app.post("/media/{media_id}/studio/add")
    async def studio_add(
        media_id: int,
        return_to: str = Form("detail"),
    ) -> RedirectResponse:
        item = db.get_media(media_id)
        if not item:
            raise HTTPException(status_code=404, detail="Not found")
        open_project = db.resolve_studio_page_project()
        if open_project is None:
            return RedirectResponse(url="/studio?msg=studio_need_project", status_code=303)
        _sid, _created = db.add_studio_item(
            item.path,
            identity_key=make_identity_key(
                item.filename, item.size_bytes, item.recorded_at
            ),
            filename=item.filename,
            recorded_at=item.recorded_at,
            kind=item.kind,
            project_id=open_project.id,
            source_media_id=item.id,
        )
        base = studio_add_return_url(media_id, return_to)
        msg = "studio_added"
        if base == "/browse" or base.startswith("/browse?"):
            return RedirectResponse(url=base, status_code=303)
        if base == "/studio" or base.startswith("/studio?"):
            return RedirectResponse(url=base, status_code=303)
        sep = "&" if "?" in base else "?"
        return RedirectResponse(url=f"{base}{sep}msg={msg}", status_code=303)

    @app.post("/studio/add-bulk")
    async def studio_add_bulk(request: Request) -> RedirectResponse:
        """Add selected Browse media IDs to the open Studio project (skip existing)."""
        form = await request.form()
        return_to = str(form.get("return_to") or "browse")
        raw_ids = form.getlist("media_ids")
        media_ids: list[int] = []
        for raw in raw_ids:
            try:
                mid = int(str(raw))
            except (TypeError, ValueError):
                continue
            if mid > 0:
                media_ids.append(mid)
        # Cap to one oversized page worth of IDs (current-page selection only).
        media_ids = media_ids[: max(BROWSE_PAGE_SIZES)]

        base = studio_bulk_return_url(return_to)
        open_project = db.resolve_studio_page_project()
        if open_project is None:
            return RedirectResponse(url="/studio?msg=studio_need_project", status_code=303)
        if not media_ids:
            return RedirectResponse(url=base, status_code=303)

        added_n, skipped_n = db.add_studio_media_ids(
            media_ids, project_id=open_project.id
        )
        dest = append_query_params(
            base,
            msg="studio_bulk_added",
            added=added_n,
            skipped=skipped_n,
        )
        return RedirectResponse(url=dest, status_code=303)

    @app.post("/api/studio/history/{direction}")
    async def api_studio_history(direction: str) -> JSONResponse:
        if direction not in {"undo", "redo"}:
            raise HTTPException(status_code=404, detail="unknown history direction")
        project = db.resolve_studio_page_project()
        if project is None:
            raise HTTPException(status_code=400, detail="no studio project open")
        changed = (
            undo_story(db, project.id)
            if direction == "undo"
            else redo_story(db, project.id)
        )
        flags = history_flags(project.id)
        if not changed:
            return JSONResponse({"ok": False, **flags}, status_code=409)
        return JSONResponse({"ok": True, **flags})

    @app.post("/studio/{studio_item_id}/remove")
    async def studio_remove(studio_item_id: int, request: Request) -> RedirectResponse:
        with story_edit(db, _clip_project_id(studio_item_id), group=_history_group(request)):
            db.remove_studio_item(studio_item_id)
        return RedirectResponse(url="/studio?msg=studio_removed", status_code=303)

    @app.post("/studio/clear")
    async def studio_clear() -> RedirectResponse:
        open_project = db.resolve_studio_page_project()
        if open_project is None:
            return RedirectResponse(url="/studio?msg=studio_need_project", status_code=303)
        db.clear_studio(open_project.id)
        return RedirectResponse(url="/studio?msg=studio_cleared", status_code=303)

    @app.post("/media/{media_id}/meta")
    async def media_meta_save(
        media_id: int,
        stars: int = Form(0),
        favorite: str | None = Form(None),
        tags: str = Form(""),
        notes: str = Form(""),
    ) -> RedirectResponse:
        item = db.get_media(media_id)
        if not item:
            raise HTTPException(status_code=404, detail="Not found")
        try:
            stars_n = max(0, min(5, int(stars)))
        except (TypeError, ValueError):
            stars_n = 0
        db.upsert_media_meta(
            item.path,
            stars=stars_n,
            favorite=bool(favorite),
            tags=parse_tags(tags),
            notes=notes or "",
            identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        )
        return RedirectResponse(
            url=f"/media/{media_id}?msg=meta_saved",
            status_code=303,
        )

    @app.post("/media/{media_id}/rename")
    async def media_rename(media_id: int, new_name: str = Form(...)) -> RedirectResponse:
        item = db.get_media(media_id)
        if not item:
            raise HTTPException(status_code=404, detail="Not found")
        try:
            result = rename_media(db, item, new_name)
            return RedirectResponse(
                url=f"/media/{result.media_id}?msg=renamed",
                status_code=303,
            )
        except RenameError as exc:
            return RedirectResponse(
                url=f"/media/{media_id}?error={quote(str(exc))}",
                status_code=303,
            )

    @app.post("/media/{media_id}/merge")
    async def media_merge(media_id: int, output_name: str = Form("")) -> RedirectResponse:
        item = db.get_media(media_id)
        if not item or not item.flow_id:
            raise HTTPException(status_code=404, detail="Not found")
        try:
            result = merge_flow(db, flow_id=item.flow_id, output_name=output_name or None)
            merged = db.find_media_by_path(str(result.output.resolve()))
            target_id = merged.id if merged else media_id
            return RedirectResponse(
                url=f"/media/{target_id}?msg=merged",
                status_code=303,
            )
        except MergeError as exc:
            return RedirectResponse(
                url=f"/media/{media_id}?error={quote(str(exc)[:300])}",
                status_code=303,
            )

    @app.get("/media/{media_id}/export/spot.geojson")
    async def media_export_spot(media_id: int) -> Response:
        """Download a local GeoJSON / .orga-spot.json — no upload."""
        item = db.get_media(media_id)
        if not item:
            raise HTTPException(status_code=404, detail="Not found")
        if item.latitude is None or item.longitude is None:
            raise HTTPException(status_code=404, detail="No GPS for this media")
        track = track_from_json(item.track_json)
        try:
            payload = build_spot_geojson(item, track)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        filename = spot_download_filename(item.filename)
        return Response(
            content=body,
            media_type="application/geo+json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    @app.get("/media/{media_id}/cached-thumb")
    async def media_cached_thumb(media_id: int) -> FileResponse:
        """Serve a thumbnail that already exists. Never creates one."""
        path = cached_thumbnail(settings.data_dir, media_id)
        if path is None:
            raise HTTPException(status_code=404, detail="No cached thumbnail")
        return FileResponse(
            path,
            media_type="image/jpeg",
            content_disposition_type="inline",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.get("/media/{media_id}/thumb")
    async def media_thumb(media_id: int) -> FileResponse:
        item = db.get_media(media_id)
        if not item:
            raise HTTPException(status_code=404, detail="Not found")
        path = resolve_media_file(db, item)
        if path is None:
            raise HTTPException(status_code=404, detail="File missing")
        # Thumb generation (ffmpeg/Pillow) is sync and can be slow — keep the
        # event loop free so concurrent range streams stay responsive.
        thumb = await asyncio.to_thread(
            ensure_thumbnail,
            media_id=item.id,
            path=path,
            kind=item.kind,
            filename=item.filename,
        )
        return FileResponse(
            thumb,
            media_type="image/jpeg",
            content_disposition_type="inline",
            headers={"Cache-Control": "private, max-age=86400"},
        )

    @app.get("/media/{media_id}/preview")
    async def media_preview(media_id: int) -> FileResponse:
        """JPEG detail preview for photos browsers cannot display natively (HEIC/…)."""
        item = db.get_media(media_id)
        if not item:
            raise HTTPException(status_code=404, detail="Not found")
        if item.kind != "photo":
            raise HTTPException(status_code=404, detail="Not a photo")
        path = resolve_media_file(db, item)
        if path is None:
            raise HTTPException(status_code=404, detail="File missing")
        if browser_can_display_photo(path):
            return file_response(path)
        try:
            preview = await asyncio.to_thread(
                ensure_photo_preview,
                media_id=item.id,
                path=path,
                filename=item.filename,
            )
        except OSError as exc:
            raise HTTPException(
                status_code=404, detail="Preview unavailable"
            ) from exc
        return FileResponse(
            preview,
            media_type="image/jpeg",
            content_disposition_type="inline",
            headers={"Cache-Control": "private, max-age=86400"},
        )

    @app.get("/media/{media_id}/stream")
    async def media_stream(media_id: int) -> Response:
        item = db.get_media(media_id)
        if not item:
            raise HTTPException(status_code=404, detail="Not found")
        path = resolve_media_file(db, item)
        if path is None:
            raise HTTPException(status_code=404, detail="File missing")
        return file_response(path)

    @app.get("/media/{media_id}/proxy")
    async def media_proxy(media_id: int) -> Response:
        item = db.get_media(media_id)
        if not item:
            raise HTTPException(status_code=404, detail="Not found")
        path = resolve_proxy_file(db, item)
        if path is None:
            # Fall back to full file for photos / videos without LRF
            path = resolve_media_file(db, item)
        if path is None:
            raise HTTPException(status_code=404, detail="File missing")
        return file_response(path)

    def _compute_duplicate_groups():
        rows = db.list_media_for_duplicates()
        inputs = [media_row_to_fingerprint(r) for r in rows]
        return find_duplicate_groups(inputs)

    @app.get("/duplicates", response_class=HTMLResponse)
    async def duplicates_page(
        request: Request,
        msg: str | None = None,
    ) -> HTMLResponse:
        groups = _compute_duplicate_groups()
        return render(
            request,
            "duplicates.html",
            groups=groups,
            group_count=len(groups),
            item_count=sum(g.size for g in groups),
            recorded_tol_s=RECORDED_AT_TOLERANCE_S,
            duration_tol_s=DURATION_TOLERANCE_S,
            flash_msg=msg,
        )

    @app.post("/duplicates/scan")
    async def duplicates_scan() -> RedirectResponse:
        # Fingerprints are derived from the current index (no file hashing).
        # Re-running after a library scan picks up new/removed paths.
        groups = await asyncio.to_thread(_compute_duplicate_groups)
        return RedirectResponse(
            url=f"/duplicates?msg=scanned&n={len(groups)}",
            status_code=303,
        )

    def _start_library_scan(
        *,
        root_id: int | None,
        work: Callable[[ProgressCallback], Any],
    ) -> RedirectResponse:
        store: ScanJobStore = app.state.scan_jobs
        job = store.try_create(root_id=root_id)
        if job is None:
            return RedirectResponse(url="/library?scan_error=busy", status_code=303)

        def runner() -> None:
            store.mark_running(job.id)

            def on_progress(progress: Any) -> None:
                store.apply_progress(job.id, progress)

            try:
                result = work(on_progress)
                store.complete(job.id, result)
            except Exception as exc:  # noqa: BLE001 — surface to UI job state
                # Avoid leaking absolute filesystem paths into the UI.
                message = f"{exc.__class__.__name__}: scan could not be completed"
                store.fail(job.id, message)

        threading.Thread(target=runner, name=f"scan-job-{job.id[:8]}", daemon=True).start()
        return RedirectResponse(url=f"/library?scan_job={job.id}", status_code=303)

    @app.get("/albums", response_class=HTMLResponse)
    async def albums_page(request: Request, msg: str | None = None) -> HTMLResponse:
        return render(
            request,
            "albums.html",
            albums=db.list_albums(),
            flash_msg=msg,
            nav_active="albums",
        )

    @app.post("/albums")
    async def albums_create(title: str = Form("")) -> RedirectResponse:
        try:
            album = db.create_album(title)
        except ValueError:
            return RedirectResponse(url="/albums?msg=album_invalid", status_code=303)
        return RedirectResponse(url=f"/albums/{album.id}?msg=album_created", status_code=303)

    @app.get("/albums/{album_id}", response_class=HTMLResponse)
    async def album_detail(
        request: Request,
        album_id: int,
        msg: str | None = None,
    ) -> HTMLResponse:
        album = db.get_album(album_id)
        if album is None:
            return render(request, "error.html", status_code=404, message="Not found")
        return render(
            request,
            "album.html",
            album=album,
            items=db.list_album_items(album_id),
            flash_msg=msg,
            nav_active="albums",
        )

    @app.post("/albums/{album_id}/rename")
    async def album_rename(album_id: int, title: str = Form("")) -> RedirectResponse:
        if db.get_album(album_id) is None:
            raise HTTPException(status_code=404, detail="Not found")
        try:
            renamed = db.rename_album(album_id, title)
        except ValueError:
            return RedirectResponse(
                url=f"/albums/{album_id}?msg=album_invalid",
                status_code=303,
            )
        if renamed is None:
            raise HTTPException(status_code=404, detail="Not found")
        return RedirectResponse(
            url=f"/albums/{album_id}?msg=album_renamed",
            status_code=303,
        )

    @app.post("/albums/{album_id}/delete")
    async def album_delete(album_id: int) -> RedirectResponse:
        if not db.delete_album(album_id):
            raise HTTPException(status_code=404, detail="Not found")
        return RedirectResponse(url="/albums?msg=album_deleted", status_code=303)

    @app.post("/albums/{album_id}/items/{item_id}/remove")
    async def album_item_remove(album_id: int, item_id: int) -> RedirectResponse:
        if db.get_album(album_id) is None:
            raise HTTPException(status_code=404, detail="Not found")
        db.remove_album_item(album_id, item_id)
        return RedirectResponse(
            url=f"/albums/{album_id}?msg=album_removed",
            status_code=303,
        )

    @app.post("/media/{media_id}/albums/add")
    async def media_album_add(
        media_id: int,
        album_id: str = Form(""),
        title: str = Form(""),
    ) -> RedirectResponse:
        item = db.get_media(media_id)
        if not item:
            raise HTTPException(status_code=404, detail="Not found")
        raw_id = (album_id or "").strip()
        target_id: int | None = None
        if raw_id:
            try:
                target_id = int(raw_id)
            except ValueError:
                target_id = None
            if target_id is None or db.get_album(target_id) is None:
                return RedirectResponse(
                    url=f"/media/{media_id}?msg=album_missing",
                    status_code=303,
                )
        else:
            try:
                target_id = db.create_album(title).id
            except ValueError:
                return RedirectResponse(
                    url=f"/media/{media_id}?msg=album_invalid",
                    status_code=303,
                )
        assert target_id is not None
        result = db.add_media_to_album(target_id, media_id)
        if result == "added":
            msg = "album_added"
        elif result == "exists":
            msg = "album_already"
        else:
            msg = "album_missing"
        return RedirectResponse(url=f"/media/{media_id}?msg={msg}", status_code=303)

    @app.post("/media/{media_id}/albums/{album_id}/remove")
    async def media_album_remove(media_id: int, album_id: int) -> RedirectResponse:
        item = db.get_media(media_id)
        if not item:
            raise HTTPException(status_code=404, detail="Not found")
        if db.get_album(album_id) is None:
            raise HTTPException(status_code=404, detail="Not found")
        db.remove_media_from_album(album_id, item.path)
        return RedirectResponse(
            url=f"/media/{media_id}?msg=album_removed",
            status_code=303,
        )

    @app.get("/library", response_class=HTMLResponse)
    async def library_page(request: Request) -> HTMLResponse:
        scan_error = request.query_params.get("scan_error")
        scan_job = request.query_params.get("scan_job")
        return render(
            request,
            "library.html",
            roots=db.list_roots(),
            source_buckets=db.source_bucket_counts(),
            scan_result=None,
            scan_error=scan_error,
            scan_job_id=scan_job,
        )

    @app.get("/api/scan-jobs/{job_id}")
    async def scan_job_status(job_id: str) -> JSONResponse:
        store: ScanJobStore = app.state.scan_jobs
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Scan job not found")
        return JSONResponse(job.to_dict())

    @app.post("/api/desktop/pick-folder")
    def pick_folder_dialog() -> JSONResponse:
        """Open a native folder picker (pywebview desktop shell only)."""
        from orga_drone.desktop import FolderPickerError, pick_folder

        try:
            path = pick_folder()
        except FolderPickerError:
            return JSONResponse(
                {
                    "status": "unavailable",
                    "error": "folder_picker_unavailable",
                },
                status_code=503,
            )
        if path is None:
            return JSONResponse({"status": "cancelled"})
        return JSONResponse({"status": "ok", "path": path})

    @app.post("/api/desktop/pick-save-file")
    async def pick_save_file_dialog(request: Request) -> JSONResponse:
        """Open a native save-file dialog (pywebview desktop shell only)."""
        from orga_drone.desktop import SaveFilePickerError, pick_save_file

        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        directory = payload.get("directory") if isinstance(payload.get("directory"), str) else ""
        filename = (
            payload.get("filename")
            if isinstance(payload.get("filename"), str)
            else "export.mp4"
        )
        try:
            path = pick_save_file(directory=directory or "", save_filename=filename or "export.mp4")
        except SaveFilePickerError:
            return JSONResponse(
                {
                    "status": "unavailable",
                    "error": "save_picker_unavailable",
                },
                status_code=503,
            )
        if path is None:
            return JSONResponse({"status": "cancelled"})
        return JSONResponse({"status": "ok", "path": path})

    @app.post("/api/desktop/pick-open-file")
    async def pick_open_file_dialog(request: Request) -> JSONResponse:
        """Open a native file-open dialog (pywebview desktop shell only)."""
        from orga_drone.desktop import OpenFilePickerError, pick_open_file

        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        directory = payload.get("directory") if isinstance(payload.get("directory"), str) else ""
        file_types_raw = payload.get("file_types")
        file_types: tuple[str, ...] | None = None
        if isinstance(file_types_raw, list) and file_types_raw:
            cleaned = tuple(
                str(item) for item in file_types_raw if isinstance(item, str) and item.strip()
            )
            if cleaned:
                file_types = cleaned
        try:
            if file_types is None:
                path = pick_open_file(directory=directory or "")
            else:
                path = pick_open_file(directory=directory or "", file_types=file_types)
        except OpenFilePickerError:
            return JSONResponse(
                {
                    "status": "unavailable",
                    "error": "open_picker_unavailable",
                },
                status_code=503,
            )
        if path is None:
            return JSONResponse({"status": "cancelled"})
        return JSONResponse({"status": "ok", "path": path})

    @app.post("/library/add")
    async def library_add(path: str = Form(...), label: str = Form("")) -> RedirectResponse:
        p = Path(path.strip().strip('"'))
        if not (p.exists() and p.is_dir()):
            return RedirectResponse(url="/library", status_code=303)
        root_id = db.add_root(p, label.strip() or None)
        return _start_library_scan(
            root_id=root_id,
            work=lambda on_progress: scan_root(db, root_id, p, on_progress=on_progress),
        )

    @app.post("/library/{root_id}/scan")
    async def library_scan(root_id: int) -> RedirectResponse:
        roots = {int(r["id"]): r for r in db.list_roots()}
        if root_id not in roots:
            return RedirectResponse(url="/library", status_code=303)
        root_path = Path(roots[root_id]["path"])
        return _start_library_scan(
            root_id=root_id,
            work=lambda on_progress: scan_root(
                db, root_id, root_path, on_progress=on_progress
            ),
        )

    @app.post("/library/scan-all")
    async def library_scan_all() -> RedirectResponse:
        return _start_library_scan(
            root_id=None,
            work=lambda on_progress: scan_all_roots(db, on_progress=on_progress),
        )

    @app.post("/library/{root_id}/remove")
    async def library_remove(root_id: int) -> RedirectResponse:
        db.remove_root(root_id)
        return RedirectResponse(url="/library", status_code=303)

    @app.get("/lang/{code}")
    async def set_lang(request: Request, code: str) -> RedirectResponse:
        lang = normalize_lang(code, settings.default_lang)
        response = RedirectResponse(url=safe_back_url(request), status_code=303)
        response.set_cookie("lang", lang, max_age=365 * 24 * 3600)
        return response

    @app.get("/theme/{mode}")
    async def set_theme(request: Request, mode: str) -> RedirectResponse:
        current = theme_from_request(request)
        prefs = ThemePrefs(
            mode=normalize_theme(mode),
            accent=current.accent,
            background=current.background,
            panel=current.panel,
        ).normalize()
        save_theme_file(settings.theme_path, prefs)
        response = RedirectResponse(url=safe_back_url(request), status_code=303)
        apply_theme_cookies(response, prefs)
        return response

    @app.post("/theme/custom")
    async def set_custom_theme(
        request: Request,
        accent: str = Form("#ff9f0a"),
        background: str = Form("#0a0c0e"),
        panel: str = Form("#14181d"),
    ) -> RedirectResponse:
        prefs = ThemePrefs(
            mode="custom",
            accent=normalize_hex(accent, "#ff9f0a"),
            background=normalize_hex(background, "#0a0c0e"),
            panel=normalize_hex(panel, "#14181d"),
        ).normalize()
        save_theme_file(settings.theme_path, prefs)
        response = RedirectResponse(url=safe_back_url(request), status_code=303)
        apply_theme_cookies(response, prefs)
        return response

    @app.get("/api/updates")
    async def api_updates_preference() -> dict[str, Any]:
        return {
            "ok": True,
            "enabled": get_check_updates(),
            "version": installed_version(),
            "download_url": OFFICIAL_DOWNLOAD_URL,
        }

    @app.post("/api/updates/preference")
    async def api_updates_set_preference(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict) or not isinstance(payload.get("enabled"), bool):
            raise HTTPException(status_code=400, detail="enabled must be a boolean")
        set_check_updates(payload["enabled"])
        return JSONResponse({"ok": True, "enabled": get_check_updates()})

    @app.post("/api/updates/check")
    async def api_updates_check(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        startup = isinstance(payload, dict) and payload.get("startup") is True
        if startup and not get_check_updates():
            return JSONResponse(
                {
                    "ok": True,
                    "checked": False,
                    "state": "skipped",
                    "current": installed_version(),
                    "latest": None,
                    "download_url": OFFICIAL_DOWNLOAD_URL,
                }
            )
        checker: UpdateChecker = app.state.update_checker
        report = await asyncio.to_thread(
            checker.check, current=installed_version(), startup=startup
        )
        body = report.as_dict()
        body["ok"] = True
        body["checked"] = True
        return JSONResponse(body)

    @app.post("/api/updates/open-download")
    async def api_updates_open_download() -> JSONResponse:
        import webbrowser

        try:
            opened = await asyncio.to_thread(webbrowser.open, OFFICIAL_DOWNLOAD_URL)
        except OSError:
            opened = False
        return JSONResponse(
            {"ok": bool(opened), "url": OFFICIAL_DOWNLOAD_URL}
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": installed_version()}

    return app
