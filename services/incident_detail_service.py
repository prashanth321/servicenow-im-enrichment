"""
Incident detail service — fetches and maps incident data from ServiceNow.

Extracted from dashboard_routes.py to separate routing from business logic
and ServiceNow API interaction. This makes the code testable and maintainable.
"""

from __future__ import annotations

from datetime import datetime, timezone

from models.dashboard_schemas import IncidentDetail
from utils.api_client import ServiceNowClient, sanitize_sysparm
from utils.logger import get_logger
from utils.sn_fields import extract_display, extract_value

logger = get_logger(__name__)


def _map_state(sn_state: str | None) -> str:
    """Map ServiceNow numeric state to our enum value."""
    mapping = {"1": "new", "2": "in_progress", "3": "on_hold", "6": "resolved", "7": "closed"}
    return mapping.get(sn_state or "", "new")


async def fetch_incident_detail(incident_number: str) -> IncidentDetail | None:
    """Fetch full incident record from SN and map to IncidentDetail.

    Returns None if the incident is not found.
    """
    safe_number = sanitize_sysparm(incident_number)
    async with ServiceNowClient() as client:
        response = await client.get(
            "/api/now/table/incident",
            params={
                "sysparm_query": f"number={safe_number}",
                "sysparm_fields": (
                    "sys_id,number,priority,state,short_description,description,"
                    "cmdb_ci,service_offering,assignment_group,assigned_to,"
                    "opened_at,opened_by,u_major_incident_manager,business_impact,"
                    "sys_created_on"
                ),
                "sysparm_display_value": "all",
                "sysparm_limit": "1",
            },
        )
        results = response.json().get("result", [])
        if not results:
            return None

        r = results[0]

        return IncidentDetail(
            sys_id=extract_value(r.get("sys_id")) or "",
            number=extract_display(r.get("number")) or incident_number,
            priority=extract_value(r.get("priority")) or "4",
            state=_map_state(extract_value(r.get("state"))),
            short_description=extract_display(r.get("short_description")) or "",
            description=extract_display(r.get("description")) or "",
            cmdb_ci=extract_value(r.get("cmdb_ci")),
            ci_name=extract_display(r.get("cmdb_ci")),
            service_offering=extract_display(r.get("service_offering")),
            assignment_group=extract_display(r.get("assignment_group")),
            assigned_to=extract_display(r.get("assigned_to")),
            opened_at=extract_display(r.get("opened_at")) or extract_display(r.get("sys_created_on")),
            opened_by=extract_display(r.get("opened_by")),
            major_incident_manager=extract_display(r.get("u_major_incident_manager")),
            business_impact=extract_display(r.get("business_impact")),
        )


async def sync_update_to_servicenow(incident_number: str, latest_entry: str = "") -> None:
    """Push the latest dashboard update to ServiceNow work_notes.

    Called after any mutation (add/update/delete) to action items, notes, or changes.
    Failures are logged but do not block the response.
    """
    try:
        incident = await fetch_incident_detail(incident_number)
        if not incident:
            logger.warning("Cannot sync — incident %s not found", incident_number)
            return

        lines: list[str] = ["=== IM Dashboard Update ==="]
        lines.append(f"Incident: {incident_number}")
        lines.append(f"Updated at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        lines.append("")

        if latest_entry:
            lines.append(latest_entry)
            lines.append("")

        lines.append("=== End Update ===")
        work_notes = "\n".join(lines)

        async with ServiceNowClient() as client:
            await client.patch(
                f"/api/now/table/incident/{incident.sys_id}",
                json_body={"work_notes": work_notes},
            )
        logger.info("Auto-synced latest update to incident %s", incident_number)
    except Exception:
        logger.warning("Auto-sync failed for %s (non-blocking)", incident_number, exc_info=True)
