"""
Incident fetch & update service.

Provides two main operations against the ServiceNow ``incident`` table:

1. **fetch_incident** — GET a single incident by ``sys_id`` and return it as a
   ``WebhookPayload`` for downstream enrichment.
2. **update_incident** — PATCH enriched fields back onto the incident record,
   including a human-readable ``work_notes`` summary.
"""

from __future__ import annotations

import httpx

from models.schemas import EnrichedIncident, UpdatePayload, WebhookPayload
from utils.api_client import ServiceNowClient
from utils.exceptions import ServiceNowAPIError
from utils.logger import get_logger


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

async def fetch_incident(
    client: ServiceNowClient,
    sys_id: str,
) -> WebhookPayload:
    """Retrieve an incident record from the ``incident`` table.

    Calls ``GET /api/now/table/incident/{sys_id}`` and maps the response into
    a ``WebhookPayload`` compatible object.

    Args:
        client: An initialised ``ServiceNowClient``.
        sys_id: The incident's ``sys_id``.

    Returns:
        A ``WebhookPayload`` populated with the incident's key fields.

    Raises:
        ServiceNowAPIError: If the API returns a non-success status.
    """
    logger = get_logger(__name__, sys_id)

    try:
        response: httpx.Response = await client.get(f"/api/now/table/incident/{sys_id}")

        if response.status_code >= 400:
            raise ServiceNowAPIError(
                f"Failed to fetch incident {sys_id}",
                status_code=response.status_code,
            )

        data: dict = response.json().get("result", {})

        def _val(field: object) -> str | None:
            """Extract a plain string value from a potentially dict-typed SN field."""
            if isinstance(field, dict):
                return field.get("value") or None
            if isinstance(field, str) and field.strip():
                return field.strip()
            return None

        payload = WebhookPayload(
            sys_id=data.get("sys_id", sys_id),
            number=data.get("number", "UNKNOWN"),
            priority=str(data.get("priority", "")),
            cmdb_ci=_val(data.get("cmdb_ci")),
            short_description=data.get("short_description", ""),
            assignment_group=_val(data.get("assignment_group")),
        )

        logger.info("Incident fetched: %s (priority=%s)", payload.number, payload.priority)
        return payload

    except ServiceNowAPIError:
        raise
    except httpx.RequestError as exc:
        logger.error("Network error fetching incident %s: %s", sys_id, exc)
        raise ServiceNowAPIError(f"Network error fetching incident {sys_id}") from exc


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def _build_work_notes(enriched: EnrichedIncident) -> str:
    """Build a multi-line work_notes string summarising the enrichment."""
    lines: list[str] = [
        "=== Automated Enrichment Summary ===",
        f"Incident: {enriched.number}",
        f"Business Impact: {enriched.business_impact}",
        f"Enrichment Status: {enriched.enrichment_status}",
    ]

    if enriched.ci_details:
        lines.append(f"CI Name: {enriched.ci_details.ci_name or 'N/A'}")
        lines.append(f"Business Application: {enriched.ci_details.business_application or 'N/A'}")
        lines.append(f"Service Mapping: {enriched.ci_details.service_mapping or 'N/A'}")
        lines.append(f"Support Group (CMDB): {enriched.ci_details.support_group or 'N/A'}")

    if enriched.oncall_details:
        lines.append(f"On-Call: {enriched.oncall_details.name or 'N/A'} "
                      f"({enriched.oncall_details.email or 'N/A'})")
        if enriched.oncall_details.escalation_contacts:
            esc_names = ", ".join(c.name for c in enriched.oncall_details.escalation_contacts)
            lines.append(f"Escalation Contacts: {esc_names}")

    if enriched.app_details:
        lines.append(f"Application Owner: {enriched.app_details.application_owner or 'N/A'}")
        lines.append(f"Technical Owner: {enriched.app_details.technical_owner or 'N/A'}")
        lines.append(f"Contact Email: {enriched.app_details.contact_email or 'N/A'}")

    lines.append("=== End Enrichment ===")
    return "\n".join(lines)


async def update_incident(
    client: ServiceNowClient,
    enriched: EnrichedIncident,
) -> bool:
    """Write enriched data back to the ServiceNow incident.

    Calls ``PATCH /api/now/table/incident/{sys_id}`` with a payload that
    includes the derived business impact, ownership fields, support group, and
    a detailed ``work_notes`` entry.

    Args:
        client: An initialised ``ServiceNowClient``.
        enriched: The fully (or partially) enriched incident data.

    Returns:
        ``True`` if the update succeeded, ``False`` otherwise.
    """
    logger = get_logger(__name__, enriched.number)

    # Build the update payload from the enriched data
    update = UpdatePayload(
        business_impact=enriched.business_impact,
        application_owner=(
            enriched.app_details.application_owner if enriched.app_details else None
        ),
        u_technical_owner=(
            enriched.app_details.technical_owner if enriched.app_details else None
        ),
        support_group=(
            enriched.ci_details.support_group if enriched.ci_details else None
        ),
        work_notes=_build_work_notes(enriched),
    )

    # Only send non-None fields to avoid blanking out existing values
    patch_body = {k: v for k, v in update.model_dump().items() if v is not None}

    try:
        response: httpx.Response = await client.patch(
            f"/api/now/table/incident/{enriched.sys_id}",
            json_body=patch_body,
        )

        if response.status_code >= 400:
            logger.error(
                "Failed to update incident %s — HTTP %s",
                enriched.number,
                response.status_code,
            )
            return False

        logger.info("Incident %s updated successfully", enriched.number)
        return True

    except (httpx.RequestError, ServiceNowAPIError) as exc:
        logger.error("Error updating incident %s: %s", enriched.number, exc)
        return False
