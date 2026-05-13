"""
Request-scoped correlation ID middleware for FastAPI.

Injects a ``X-Request-ID`` UUID into every request's ``state`` and
response headers so log lines from the same request can be correlated.

The ID is stored in a :class:`contextvars.ContextVar` so that any logger
in the call-chain can include it via :func:`get_correlation_id`.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")

HEADER = "X-Request-ID"


def get_correlation_id() -> str:
    """Return the correlation ID for the current request context."""
    return _correlation_id.get()


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Assign a unique ID to each inbound request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        req_id = request.headers.get(HEADER) or str(uuid.uuid4())
        _correlation_id.set(req_id)
        request.state.correlation_id = req_id
        response = await call_next(request)
        response.headers[HEADER] = req_id
        return response
