"""Allow only loopback Host and same-origin mutations (Issue #136).

The desktop window and a local browser talk to 127.0.0.1. A page on another
site, or a request that names a different Host, must not read the library or
change it. GET and HEAD without Origin stay allowed for the first load and
for WebView2. Writes without a trusted Origin are refused.
"""

from __future__ import annotations

from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]", "testserver"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def host_name(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw.startswith("[") and "]" in raw:
        return raw[: raw.index("]") + 1]
    return raw.split(":", 1)[0]


def origin_host(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return ""
    host = (parsed.hostname or "").lower()
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def trusted_host(host: str) -> bool:
    name = host_name(host)
    return name in LOOPBACK_HOSTS


def trusted_origin(origin: str, host: str) -> bool:
    remote = origin_host(origin)
    local = host_name(host)
    if not remote or not trusted_host(remote):
        return False
    if not local:
        return True
    aliases = {"127.0.0.1", "localhost", "::1", "[::1]", "testserver"}
    if remote in aliases and local in aliases:
        return True
    return remote == local


class LoopbackOriginMiddleware(BaseHTTPMiddleware):
    """Reject a foreign Host on every request and a foreign Origin on writes."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        host = request.headers.get("host") or ""
        if not trusted_host(host):
            return JSONResponse({"detail": "Host is not allowed"}, status_code=403)
        origin = request.headers.get("origin") or ""
        if request.method.upper() in SAFE_METHODS:
            if origin and not trusted_origin(origin, host):
                return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
            return await call_next(request)
        site = (request.headers.get("sec-fetch-site") or "").lower()
        if site in {"cross-site", "none"} and origin:
            if not trusted_origin(origin, host):
                return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
        if origin:
            if not trusted_origin(origin, host):
                return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
            return await call_next(request)
        if site in {"same-origin", "same-site", ""}:
            return await call_next(request)
        return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
