"""
CMDB / Configuration Item lookup service.

Fetches CI details from the ServiceNow ``cmdb_ci`` table and maps them into
the ``CIDetails`` schema used by downstream enrichment steps.
"""

from __future__ import annotations

import httpx

from models.schemas import CIDetails
from utils.api_client import ServiceNowClient
from utils.exceptions import CINotFoundError, ServiceNowAPIError
from utils.logger import get_logger


async def fetch_ci_details(
    client: ServiceNowClient,
    ci_sys_id: str,
    incident_number: str = "N/A",
) -> CIDetails:
    """Retrieve Configuration Item details from the CMDB.

    Calls ``GET /api/now/table/cmdb_ci/{ci_sys_id}`` and extracts the fields
    required for enrichment.

    Args:
        client: An initialised ``ServiceNowClient``.
        ci_sys_id: The ``sys_id`` of the configuration item.
        incident_number: Used for contextual logging.

    Returns:
        A populated ``CIDetails`` instance.

    Raises:
        CINotFoundError: If the CI record does not exist in the CMDB.
        ServiceNowAPIError: If the API returns a non-success status.
    """
    logger = get_logger(__name__, incident_number)

    try:
        # Fetch the CI record from the CMDB table
        response: httpx.Response = await client.get(f"/api/now/table/cmdb_ci/{ci_sys_id}")

        if response.status_code == 404:
            raise CINotFoundError(f"CI {ci_sys_id} not found in CMDB")

        if response.status_code >= 400:
            raise ServiceNowAPIError(
                f"CMDB lookup failed for CI {ci_sys_id}",
                status_code=response.status_code,
            )

        data: dict = response.json().get("result", {})

        # ServiceNow may return linked fields as dicts with a "value" key or
        # as plain strings — normalise both cases.
        def _extract(field_value: object) -> str | None:
            """Return a string value or None for empty / dict-typed fields."""
            if isinstance(field_value, dict):
                return field_value.get("value") or field_value.get("display_value") or None
            if isinstance(field_value, str) and field_value.strip():
                return field_value.strip()
            return None

        ci_details = CIDetails(
            ci_name=_extract(data.get("name")),
            business_application=_extract(data.get("business_criticality"))
                or _extract(data.get("u_business_application")),
            service_mapping=_extract(data.get("service_classification"))
                or _extract(data.get("u_service_mapping")),
            support_group=_extract(data.get("support_group")),
        )

        logger.info("CI details fetched for %s: ci_name=%s", ci_sys_id, ci_details.ci_name)
        return ci_details

    except (CINotFoundError, ServiceNowAPIError):
        raise
    except httpx.RequestError as exc:
        logger.error("Network error fetching CI %s: %s", ci_sys_id, exc)
        raise ServiceNowAPIError(f"Network error fetching CI {ci_sys_id}") from exc
