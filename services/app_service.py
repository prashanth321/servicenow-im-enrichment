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
from utils.sn_fields import extract_display


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

        app_details = AppDetails(
            application_owner=extract_display(data.get("owned_by")) or extract_display(data.get("application_owner")),
            technical_owner=extract_display(data.get("managed_by")) or extract_display(data.get("u_technical_owner")),
            contact_email=extract_display(data.get("u_contact_email")) or extract_display(data.get("email")),
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
