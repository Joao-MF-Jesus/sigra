from __future__ import annotations

import logging
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import public_demo_mode


LOGGER = logging.getLogger("sigra.http")

STATELESS_WRITE_ROUTES = frozenset(
    {
        "/recommendations",
        "/financing/simulate",
        "/financing/reverse-simulate",
        "/financing/compare",
        "/motorcycles/recommendations",
        "/api/v1/academic-cohort/evaluate",
    }
)
PRIVATE_READ_PREFIXES = (
    "/api/v1/test-runs",
    "/api/v1/admin",
    "/auth",
    "/users",
    "/expenses",
    "/maintenances",
    "/user-vehicles",
    "/vehicle-reports",
    "/fuel-consumption-reports",
    "/vehicle-statistics",
    "/reports",
)
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _demo_denied_response() -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "detail": {
                "code": "demo_read_only",
                "message": (
                    "Ambiente demonstrativo em modo somente leitura."
                ),
            }
        },
    )


def request_is_allowed_in_public_demo(method: str, path: str) -> bool:
    normalized_method = method.upper()
    if normalized_method in {"HEAD", "OPTIONS"}:
        return True
    if normalized_method == "GET":
        return not path.startswith(PRIVATE_READ_PREFIXES)
    return normalized_method == "POST" and path in STATELESS_WRITE_ROUTES


class PublicDemoReadOnlyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, enabled: bool | None = None):
        super().__init__(app)
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next):
        enabled = public_demo_mode() if self.enabled is None else self.enabled
        if enabled and not request_is_allowed_in_public_demo(
            request.method,
            request.url.path,
        ):
            return _demo_denied_response()
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = uuid4().hex
        request.state.request_id = request_id
        started_at = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            LOGGER.info(
                (
                    "request_completed timestamp=%s request_id=%s method=%s "
                    "path=%s status=%s duration_ms=%.2f"
                ),
                datetime.now(timezone.utc).isoformat(),
                request_id,
                request.method,
                request.url.path,
                status_code,
                (perf_counter() - started_at) * 1000,
            )
