"""FastAPI application – local web UI for orga-drone."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from orga_drone import __version__
from orga_drone.config import settings
from orga_drone.db import Database, track_from_json
from orga_drone.i18n import SUPPORTED_LANGS, get_translator, normalize_lang
from orga_drone.media_files import resolve_media_file, resolve_proxy_file
from orga_drone.ops.merge import MergeError, default_merge_name, ffmpeg_available, merge_flow
from orga_drone.ops.rename import RenameError, rename_media
from orga_drone.scan import scan_all_roots, scan_root
from orga_drone.thumbs import ensure_thumbnail

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

MIME_BY_SUFFIX = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".lrf": "video/mp4",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
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


def create_app() -> FastAPI:
    settings.ensure_dirs()
    db = Database(settings.db_path)

    app = FastAPI(title="orga-drone", version=__version__)
    app.state.db = db

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["filesize"] = format_bytes
    templates.env.filters["duration"] = format_duration

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def lang_from_request(request: Request) -> str:
        cookie = request.cookies.get("lang")
        return normalize_lang(cookie, settings.default_lang)

    def view_from_request(request: Request, override: str | None = None) -> str:
        raw = (override or request.cookies.get("view") or "grid").lower()
        return raw if raw in {"grid", "list"} else "grid"

    def ctx(request: Request, **extra: Any) -> dict[str, Any]:
        lang = lang_from_request(request)
        _ = get_translator(lang)
        return {
            "request": request,
            "lang": lang,
            "langs": SUPPORTED_LANGS,
            "_": _,
            "version": __version__,
            "stats": db.stats(),
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
        media_type = MIME_BY_SUFFIX.get(path.suffix.lower(), "application/octet-stream")
        return FileResponse(
            path,
            media_type=media_type,
            filename=path.name,
            content_disposition_type="inline",
        )

    @app.get("/", response_class=HTMLResponse)
    async def index(
        request: Request,
        sort: str = Query("recorded_at"),
        order: str = Query("desc"),
        drone: str | None = None,
        kind: str | None = None,
        gps: str | None = None,
        flows: str | None = None,
        q: str | None = None,
        view: str | None = None,
    ) -> HTMLResponse:
        has_gps = {"yes": True, "no": False}.get(gps or "")
        flows_only = {"yes": True, "no": False}.get(flows or "")
        current_view = view_from_request(request, view)
        items = db.list_media(
            sort=sort,
            order=order,
            drone=drone or None,
            kind=kind or None,
            has_gps=has_gps,
            flows_only=flows_only,
            q=q or None,
        )
        response = render(
            request,
            "index.html",
            items=items,
            drones=db.distinct_drones(),
            view=current_view,
            filters={
                "sort": sort,
                "order": order,
                "drone": drone or "",
                "kind": kind or "",
                "gps": gps or "",
                "flows": flows or "",
                "q": q or "",
                "view": current_view,
            },
        )
        if view in {"grid", "list"}:
            response.set_cookie("view", view, max_age=365 * 24 * 3600)
        return response

    @app.get("/media/{media_id}", response_class=HTMLResponse)
    async def media_detail(
        request: Request,
        media_id: int,
        msg: str | None = None,
        error: str | None = None,
    ) -> HTMLResponse:
        item = db.get_media(media_id)
        if not item:
            return render(request, "error.html", status_code=404, message="Not found")
        clips = db.flow_clips(item.flow_id) if item.flow_id else []
        multi_flow = bool(item.flow_id and item.clip_count and item.clip_count > 1)
        if not multi_flow and item.flow_id and len(clips) > 1:
            multi_flow = True
        track = track_from_json(item.track_json)
        map_link = (
            osm_link(item.latitude, item.longitude)
            if item.latitude is not None and item.longitude is not None
            else None
        )
        media_path = resolve_media_file(db, item)
        proxy_path = resolve_proxy_file(db, item) if item.kind == "video" else None
        stem = Path(item.filename).stem
        return render(
            request,
            "detail.html",
            item=item,
            clips=clips,
            track=track,
            osm_url=map_link,
            can_play=media_path is not None,
            has_proxy=proxy_path is not None,
            can_merge=multi_flow and item.kind == "video",
            ffmpeg_ok=ffmpeg_available(),
            merge_default_name=default_merge_name(item) if item.kind == "video" else "",
            rename_stem=stem,
            flash_msg=msg,
            flash_error=error,
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

    @app.get("/media/{media_id}/thumb")
    async def media_thumb(media_id: int) -> FileResponse:
        item = db.get_media(media_id)
        if not item:
            raise HTTPException(status_code=404, detail="Not found")
        path = resolve_media_file(db, item)
        if path is None:
            raise HTTPException(status_code=404, detail="File missing")
        thumb = ensure_thumbnail(
            media_id=item.id,
            path=path,
            kind=item.kind,
            filename=item.filename,
        )
        return FileResponse(thumb, media_type="image/jpeg", content_disposition_type="inline")

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

    @app.get("/library", response_class=HTMLResponse)
    async def library_page(request: Request) -> HTMLResponse:
        return render(request, "library.html", roots=db.list_roots(), scan_result=None)

    @app.post("/library/add")
    async def library_add(path: str = Form(...), label: str = Form("")) -> RedirectResponse:
        p = Path(path.strip().strip('"'))
        if p.exists() and p.is_dir():
            root_id = db.add_root(p, label.strip() or None)
            scan_root(db, root_id, p)
        return RedirectResponse(url="/library", status_code=303)

    @app.post("/library/{root_id}/scan")
    async def library_scan(root_id: int) -> RedirectResponse:
        roots = {int(r["id"]): r for r in db.list_roots()}
        if root_id in roots:
            scan_root(db, root_id, Path(roots[root_id]["path"]))
        return RedirectResponse(url="/library", status_code=303)

    @app.post("/library/scan-all")
    async def library_scan_all() -> RedirectResponse:
        scan_all_roots(db)
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

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app
