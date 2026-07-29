"""FastAPI application – local web UI for orga-drone."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from orga_drone import __version__
from orga_drone.config import settings
from orga_drone.db import Database, make_identity_key, parse_tags, track_from_json
from orga_drone.dupes import (
    DURATION_TOLERANCE_S,
    RECORDED_AT_TOLERANCE_S,
    find_duplicate_groups,
    media_row_to_fingerprint,
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
from orga_drone.scan import scan_all_roots, scan_root
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
from orga_drone.thumbs import ensure_thumbnail

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


def create_app() -> FastAPI:
    settings.ensure_dirs()
    db = Database(settings.db_path)

    app = FastAPI(title="orga-drone", version=__version__)
    app.state.db = db

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
        return raw if raw in {"grid", "list"} else "grid"

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

    def ctx(request: Request, **extra: Any) -> dict[str, Any]:
        lang = lang_from_request(request)
        _ = get_translator(lang)
        theme = theme_from_request(request)
        return {
            "request": request,
            "lang": lang,
            "langs": SUPPORTED_LANGS,
            "_": _,
            "version": __version__,
            "stats": db.stats(),
            "theme": theme.mode,
            "theme_accent": theme.accent,
            "theme_bg": theme.background,
            "theme_panel": theme.panel,
            "theme_style": custom_css_vars(theme) if theme.mode == "custom" else "",
            "nav_active": "",
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
        return FileResponse(
            path,
            media_type=media_type,
            filename=path.name,
            content_disposition_type="inline",
            headers={
                "Accept-Ranges": "bytes",
                "Cache-Control": "private, max-age=3600",
            },
        )

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        """Welcome hub — stats, CTAs, recent/favorites shortcuts."""
        recent = db.list_media(sort="recorded_at", order="desc")[:8]
        favorites = db.list_media(sort="recorded_at", order="desc", favorite=True)[:8]
        return render(
            request,
            "dashboard.html",
            recent=recent,
            favorites=favorites,
            nav_active="dashboard",
        )

    @app.get("/dashboard")
    async def dashboard_alias() -> RedirectResponse:
        return RedirectResponse(url="/", status_code=303)

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
        resolved_kind = search.kind
        resolved_q = search.effective_q()
        resolved_from = search.date_from
        resolved_to = search.date_to
        items = db.list_media(
            sort=sort,
            order=order,
            drone=drone or None,
            kind=resolved_kind,
            source=source or None,
            has_gps=has_gps,
            flows_only=flows_only,
            sessions_only=sessions_only,
            favorite=favorite_only,
            q=resolved_q,
            date_from=resolved_from,
            date_to=resolved_to,
        )
        favorite_filter = favorite or ""
        if not favorite_filter and search.favorite is True:
            favorite_filter = "yes"
        response = render(
            request,
            "index.html",
            items=items,
            drones=db.distinct_drones(),
            view=current_view,
            nav_active="browse",
            ask_summary=search.summary_parts() if ask_text else [],
            filters={
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
            },
        )
        if view in {"grid", "list"}:
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
            can_merge=multi_flow and item.kind == "video",
            ffmpeg_ok=ffmpeg_available(),
            merge_default_name=default_merge_name(item) if item.kind == "video" else "",
            rename_stem=stem,
            flash_msg=msg,
            flash_error=error,
        )

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

    @app.get("/library", response_class=HTMLResponse)
    async def library_page(request: Request) -> HTMLResponse:
        return render(request, "library.html", roots=db.list_roots(), scan_result=None)

    @app.post("/library/add")
    async def library_add(path: str = Form(...), label: str = Form("")) -> RedirectResponse:
        p = Path(path.strip().strip('"'))
        if p.exists() and p.is_dir():
            root_id = db.add_root(p, label.strip() or None)
            await asyncio.to_thread(scan_root, db, root_id, p)
        return RedirectResponse(url="/library", status_code=303)

    @app.post("/library/{root_id}/scan")
    async def library_scan(root_id: int) -> RedirectResponse:
        roots = {int(r["id"]): r for r in db.list_roots()}
        if root_id in roots:
            await asyncio.to_thread(
                scan_root, db, root_id, Path(roots[root_id]["path"])
            )
        return RedirectResponse(url="/library", status_code=303)

    @app.post("/library/scan-all")
    async def library_scan_all() -> RedirectResponse:
        await asyncio.to_thread(scan_all_roots, db)
        return RedirectResponse(url="/library", status_code=303)

    @app.post("/library/{root_id}/remove")
    async def library_remove(root_id: int) -> RedirectResponse:
        db.remove_root(root_id)
        return RedirectResponse(url="/library", status_code=303)

    @app.get("/lang/{code}")
    async def set_lang(code: str) -> RedirectResponse:
        lang = normalize_lang(code, settings.default_lang)
        response = RedirectResponse(url="/", status_code=303)
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

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app
