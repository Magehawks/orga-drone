"""Allow only loopback Host and same-origin mutations (Issue #136).

The desktop window loads ``http://127.0.0.1:<port>/`` in WebView2. Chromium
sends ``Origin: http://127.0.0.1:<port>`` and ``Sec-Fetch-Site: same-origin``
on ``fetch()`` writes from that document. GET/HEAD without Origin stay allowed
for the first navigation.

A write is allowed only when:
- ``Origin`` matches the request scheme, host, and port, or
- ``Origin`` is absent and both ``Sec-Fetch-Site: same-origin`` and ``Referer``
  match that same scheme, host, and port (narrow desktop fallback).

Missing Origin and Sec-Fetch-Site together is refused. ``localhost`` is not an
alias for ``127.0.0.1``.
"""

from __future__ import annotations

from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]", "testserver"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
OriginKey = tuple[str, str, int]


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def host_name(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw.startswith("[") and "]" in raw:
        name = raw[: raw.index("]") + 1]
        inner = name[1:-1]
        return inner
    return raw.split(":", 1)[0]


def host_port(host_header: str, scheme: str) -> int:
    raw = (host_header or "").strip().lower()
    if raw.startswith("[") and "]" in raw:
        rest = raw[raw.index("]") + 1 :]
        if rest.startswith(":") and rest[1:].isdigit():
            return int(rest[1:])
        return _default_port(scheme)
    if raw.count(":") == 1:
        _name, port_s = raw.split(":")
        if port_s.isdigit():
            return int(port_s)
    return _default_port(scheme)


def request_identity(scheme: str, host_header: str) -> OriginKey | None:
    scheme_n = (scheme or "").strip().lower()
    if scheme_n not in {"http", "https"}:
        return None
    host = host_name(host_header)
    if not host or not trusted_host(host_header):
        return None
    return scheme_n, host, host_port(host_header, scheme_n)


def origin_identity(value: str) -> OriginKey | None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    port = parsed.port if parsed.port is not None else _default_port(parsed.scheme)
    return parsed.scheme, host, port


def trusted_host(host: str) -> bool:
    name = host_name(host)
    if name in LOOPBACK_HOSTS:
        return True
    return f"[{name}]" in LOOPBACK_HOSTS


def trusted_origin(origin: str, host: str, *, scheme: str = "http") -> bool:
    """True when Origin scheme, host, and port equal the request Host."""
    remote = origin_identity(origin)
    local = request_identity(scheme, host)
    return remote is not None and local is not None and remote == local


def _forbidden(detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=403)


def write_is_allowed(request: Request) -> bool:
    """Desktop ``fetch`` sends Origin; missing both Origin and Sec-Fetch-Site is not enough."""
    host = request.headers.get("host") or ""
    scheme = request.url.scheme
    local = request_identity(scheme, host)
    if local is None:
        return False
    origin = (request.headers.get("origin") or "").strip()
    if origin:
        return origin_identity(origin) == local
    site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    if site != "same-origin":
        return False
    referer = (request.headers.get("referer") or "").strip()
    return origin_identity(referer) == local


class LoopbackOriginMiddleware(BaseHTTPMiddleware):
    """Reject a foreign Host on every request and untrusted writes."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        host = request.headers.get("host") or ""
        if not trusted_host(host):
            return _forbidden("Host is not allowed")
        origin = (request.headers.get("origin") or "").strip()
        if request.method.upper() in SAFE_METHODS:
            if origin and origin_identity(origin) != request_identity(
                request.url.scheme, host
            ):
                return _forbidden("Origin is not allowed")
            return await call_next(request)
        if not write_is_allowed(request):
            return _forbidden("Origin is not allowed")
        return await call_next(request)
