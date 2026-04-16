"""
Business Application metadata lookup service.

Fetches ownership and contact information from the ``cmdb_ci_business_app``
table.
"""

from __future__ import annotations

import httpx

from models.schemas import AppDetails
from utils.api_client import ServiceNowClient
from utils.exceptions import ServiceNowAPIError
from utils.logger import get_logger


async def fetch_app_details(
    client: ServiceNowClient,
    app_sys_id: str,
    incident_number: str = "N/A",
) -> AppDetails:
    """Retrieve business application ownership details.

    Calls ``GET /api/now/table/cmdb_ci_business_app/{app_sys_id}``.

    Args:
        client: An initialised ``ServiceNowClient``.
        app_sys_id: The ``sys_id`` of the business application CI.
        incident_number: Used for contextual logging.

    Returns:
        An ``AppDetails`` instance with owner and contact info.

    Raises:
        ServiceNowAPIError: If the API returns a non-success status.
    """
    logger = get_logger(__name__, incident_number)

    try:
        # Fetch the business application record
        response: httpx.Response = await client.get(
            f"/api/now/table/cmdb_ci_business_app/{app_sys_id}",
        )

        if response.status_code >= 400:
            raise ServiceNowAPIError(
                f"Business app lookup failed for {app_sys_id}",
                status_code=response.status_code,
            )

        data: dict = response.json().get("result", {})

        def _extract(field_value: object) -> str | None:
            """Normalise dict-typed or string-typed ServiceNow field values."""
            if isinstance(field_value, dict):
                return field_value.get("display_value") or field_value.get("value") or None
            if isinstance(field_value, str) and field_value.strip():
                return field_value.strip()
            return None

        app_details = AppDetails(
            application_owner=_extract(data.get("owned_by")) or _extract(data.get("application_owner")),
            technical_owner=_extract(data.get("managed_by")) or _extract(data.get("u_technical_owner")),
            contact_email=_extract(data.get("u_contact_email")) or _extract(data.get("email")),
        )

        logger.info(
            "App details fetched for %s: owner=%s",
            app_sys_id,
            app_details.application_owner,
        )
        return app_details

    except ServiceNowAPIError:
        raise
    except httpx.RequestError as exc:
        logger.error("Network error fetching app %s: %s", app_sys_id, exc)
        raise ServiceNowAPIError(f"Network error fetching app {app_sys_id}") from exc
