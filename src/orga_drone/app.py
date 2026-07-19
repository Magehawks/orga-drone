"""FastAPI application – local web UI for orga-drone."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from orga_drone import __version__
from orga_drone.config import settings
from orga_drone.db import Database, track_from_json
from orga_drone.i18n import SUPPORTED_LANGS, get_translator, normalize_lang
from orga_drone.scan import scan_all_roots, scan_root

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"


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
    ) -> HTMLResponse:
        has_gps = {"yes": True, "no": False}.get(gps or "")
        flows_only = {"yes": True, "no": False}.get(flows or "")
        items = db.list_media(
            sort=sort,
            order=order,
            drone=drone or None,
            kind=kind or None,
            has_gps=has_gps,
            flows_only=flows_only,
            q=q or None,
        )
        return render(
            request,
            "index.html",
            items=items,
            drones=db.distinct_drones(),
            filters={
                "sort": sort,
                "order": order,
                "drone": drone or "",
                "kind": kind or "",
                "gps": gps or "",
                "flows": flows or "",
                "q": q or "",
            },
        )

    @app.get("/media/{media_id}", response_class=HTMLResponse)
    async def media_detail(request: Request, media_id: int) -> HTMLResponse:
        item = db.get_media(media_id)
        if not item:
            return render(request, "error.html", status_code=404, message="Not found")
        clips = db.flow_clips(item.flow_id) if item.flow_id else []
        track = track_from_json(item.track_json)
        map_link = (
            osm_link(item.latitude, item.longitude)
            if item.latitude is not None and item.longitude is not None
            else None
        )
        return render(
            request,
            "detail.html",
            item=item,
            clips=clips,
            track=track,
            osm_url=map_link,
        )

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
