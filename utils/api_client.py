"""
Async HTTP client for ServiceNow REST API calls.

Wraps ``httpx.AsyncClient`` with:
* Basic authentication sourced from application settings.
* 10-second request timeout.
* Automatic retry (3 attempts, exponential back-off) on transient errors
  (connection failures, HTTP 429 / 500 / 503) via ``tenacity``.
"""

from __future__ import annotations

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    retry_if_result,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


def sanitize_sysparm(value: str) -> str:
    """Strip characters that could inject additional SYSPARM filter clauses.

    ServiceNow uses ``^`` as a logical AND separator in encoded queries.
    Allowing user input to contain ``^`` lets an attacker append extra
    filter conditions.  This function removes ``^`` and ``\\n`` from the
    value so it can be safely embedded in a sysparm_query.
    """
    return value.replace("^", "").replace("\n", "").replace("\r", "")


def _is_retryable_response(response: httpx.Response) -> bool:
    """Return True when the HTTP status code warrants a retry."""
    return response.status_code in {429, 500, 503}


# Retry decorator applied to the low-level request helper
_retry_decorator = retry(
    retry=(
        retry_if_exception_type(httpx.RequestError)
        | retry_if_result(_is_retryable_response)
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)


class ServiceNowClient:
    """Async HTTP client pre-configured for the target ServiceNow instance.

    Usage::

        async with ServiceNowClient() as client:
            resp = await client.get("/api/now/table/incident", params={...})
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "ServiceNowClient":
        self._client = httpx.AsyncClient(
            base_url=settings.sn_base_url,
            auth=(settings.sn_username, settings.sn_password),
            timeout=httpx.Timeout(10.0),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # HTTP verbs — each wrapped with the tenacity retry decorator
    # ------------------------------------------------------------------

    @_retry_decorator
    async def get(
        self,
        path: str,
        params: dict | None = None,
    ) -> httpx.Response:
        """Send a GET request to the ServiceNow REST API.

        Args:
            path: API path relative to the instance base URL.
            params: Optional query parameters.

        Returns:
            The ``httpx.Response`` object.
        """
        if self._client is None:
            raise RuntimeError("Client not initialised — use `async with`")
        response = await self._client.get(path, params=params)
        return response

    async def patch(
        self,
        path: str,
        json_body: dict,
    ) -> httpx.Response:
        """Send a PATCH request to the ServiceNow REST API.

        Mutations are **not** retried to avoid duplicate side-effects
        (e.g. duplicate work_notes or re-triggering business rules).

        Args:
            path: API path relative to the instance base URL.
            json_body: JSON-serialisable dict for the request body.

        Returns:
            The ``httpx.Response`` object.
        """
        if self._client is None:
            raise RuntimeError("Client not initialised — use `async with`")
        response = await self._client.patch(path, json=json_body)
        return response
