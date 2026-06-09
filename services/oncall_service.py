"""
On-call rota lookup service.

Queries the ServiceNow ``on_call_rota`` endpoint to determine who is currently
on call for a given support group, along with their escalation contacts.
"""

from __future__ import annotations

import httpx

from models.schemas import EscalationContact, OnCallDetails
from utils.api_client import ServiceNowClient
from utils.exceptions import OnCallFetchError, ServiceNowAPIError
from utils.logger import get_logger


async def fetch_oncall_details(
    client: ServiceNowClient,
    support_group: str,
    incident_number: str = "N/A",
) -> OnCallDetails:
    """Fetch the current on-call user and escalation contacts for *support_group*.

    Calls ``GET /api/now/on_call_rota/whoisoncall`` with the group as a query
    parameter.

    Args:
        client: An initialised ``ServiceNowClient``.
        support_group: The sys_id or name of the support group.
        incident_number: Used for contextual logging.

    Returns:
        An ``OnCallDetails`` instance (may have empty fields if data missing).

    Raises:
        OnCallFetchError: If the API response cannot be parsed.
        ServiceNowAPIError: If the API returns a non-success status.
    """
    logger = get_logger(__name__, incident_number)

    try:
        # Query the on-call rota API, filtering by group
        response: httpx.Response = await client.get(
            "/api/now/on_call_rota/whoisoncall",
            params={"group": support_group},
        )

        if response.status_code >= 400:
            raise ServiceNowAPIError(
                f"On-call lookup failed for group {support_group}",
                status_code=response.status_code,
            )

        result: dict = response.json().get("result", {})

        # The API may return a list of on-call users — pick the first as primary
        users: list[dict] = result if isinstance(result, list) else result.get("users", [])

        if not users:
            logger.warning("No on-call users found for group %s", support_group)
            return OnCallDetails()

        primary = users[0] if users else {}

        # Build escalation contact list from remaining users
        escalation_contacts: list[EscalationContact] = [
            EscalationContact(
                name=u.get("name", "Unknown"),
                email=u.get("email"),
                phone=u.get("phone"),
            )
            for u in users[1:]
        ]

        oncall = OnCallDetails(
            name=primary.get("name"),
            email=primary.get("email"),
            phone=primary.get("phone"),
            escalation_contacts=escalation_contacts,
        )

        logger.info("On-call fetched for group %s: primary=%s", support_group, oncall.name)
        return oncall

    except (OnCallFetchError, ServiceNowAPIError):
        raise
    except httpx.RequestError as exc:
        logger.error("Network error fetching on-call for group %s: %s", support_group, exc)
        raise OnCallFetchError(f"Network error fetching on-call for group {support_group}") from exc
    except (KeyError, TypeError, IndexError) as exc:
        logger.error("Unexpected on-call response structure for group %s: %s", support_group, exc)
        raise OnCallFetchError(f"Unexpected response structure for group {support_group}") from exc
