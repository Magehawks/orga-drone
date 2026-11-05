"""Narrow HTTP boundary for the opt-in local Control API and Studio bridge."""

from __future__ import annotations

import ipaddress
import json
from typing import Any

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from orga_drone.control import ControlError, ControlService
from orga_drone.local_http import write_is_allowed

MAX_BODY_BYTES = 8192


def loopback(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return value == "localhost"


def control_router(service: ControlService, bind_host: str) -> APIRouter:
    router = APIRouter()

    async def body(request: Request) -> Any:
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_BODY_BYTES:
                raise ControlError("PAYLOAD_TOO_LARGE", 413)
            data.extend(chunk)
        try:
            return json.loads(data)
        except (ValueError, UnicodeError, RecursionError):
            raise ControlError("INVALID_JSON", 400) from None

    def check(request: Request, *, external: bool) -> None:
        peer = request.client.host if request.client else ""
        # testclient is Starlette's in-process transport, not a network peer.
        if not loopback(bind_host) or (not loopback(peer) and peer != "testclient"):
            raise ControlError("LOOPBACK_REQUIRED", 403)
        if external:
            service.authenticate(request.headers.get("authorization", ""))
        elif not write_is_allowed(request):
            raise ControlError("ORIGIN_REQUIRED", 403)

    def response(value: Any) -> JSONResponse:
        return JSONResponse(value, headers={"Cache-Control": "no-store"})

    @router.get("/api/control/v1/editor-state")
    async def editor_state(request: Request) -> JSONResponse:
        check(request, external=True)
        return response(service.editor_state())

    @router.get("/api/control/v1/available-controls")
    async def available_controls(request: Request) -> JSONResponse:
        check(request, external=True)
        return response(service.available_controls())

    @router.get("/api/control/v1/actions")
    async def available_actions(request: Request) -> JSONResponse:
        check(request, external=True)
        return response(service.available_actions())

    @router.post("/api/control/v1/commands")
    async def commands(request: Request) -> JSONResponse:
        check(request, external=True)
        return response(service.submit(await body(request)))

    @router.post("/api/control/v1/read-actions")
    async def read_actions(request: Request) -> JSONResponse:
        check(request, external=True)
        return response(service.read_action(await body(request)))

    @router.get("/api/control/v1/commands/{command_id}")
    async def command_result(command_id: str, request: Request) -> JSONResponse:
        check(request, external=True)
        return response(service.external_result(command_id))

    @router.post("/api/studio/control/{action}")
    async def bridge(action: str, request: Request) -> JSONResponse:
        check(request, external=False)
        payload = await body(request)
        if action == "enable":
            return response(service.enable(payload))
        if action == "disable":
            from orga_drone.control import shape

            shape(payload, set())
            return response(service.disable())
        operations = {
            "poll": service.poll,
            "resume": service.resume,
            "execute": service.execute,
            "recover": service.recover,
            "ack": service.acknowledge,
        }
        if action not in operations:
            raise ControlError("UNKNOWN_OPERATION", 404)
        return response(operations[action](payload))

    return router
