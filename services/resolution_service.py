"""
Incident resolution service.

Handles the two-phase resolution workflow:
1. Accept a meeting transcript and generate an AI-style summary.
2. Build resolution artefacts (chronology, actions, problem ticket)
   and post to a knowledge base (Confluence stub).

Converted from IncidentResolutionModal.tsx.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from models.dashboard_schemas import ResolutionRequest, ResolutionSummary
from utils.api_client import ServiceNowClient
from utils.exceptions import ServiceNowAPIError
from utils.logger import get_logger

# In-memory store: incident_number -> ResolutionSummary
_resolution_store: dict[str, ResolutionSummary] = {}

logger = get_logger(__name__)


def generate_summary(
    incident_number: str,
    transcript: str,
    incident_context: dict | None = None,
) -> ResolutionSummary:
    """Generate a resolution summary from a meeting transcript.

    In production this would call an LLM API. The current implementation
    produces a structured summary template similar to the React mock.

    Args:
        incident_number: The incident being resolved.
        transcript: Raw meeting transcript text.
        incident_context: Optional dict with incident metadata.

    Returns:
        A populated ResolutionSummary.
    """
    ctx = incident_context or {}
    description = ctx.get("short_description", "Incident")
    problem_ticket = f"PRB{uuid.uuid4().hex[:7].upper()}"

    summary = ResolutionSummary(
        summary=(
            f"Incident {incident_number} — {description}\n\n"
            "Root cause was identified and a fix has been applied. "
            "Services have been restored to normal operation. "
            "A problem ticket has been raised for permanent resolution."
        ),
        root_cause=(
            "Analysis of the transcript indicates the issue was caused by "
            "a configuration change that impacted service availability. "
            "The change was rolled back and services recovered."
        ),
        people_chronology=[
            {"time": "T+0 min", "event": "Incident declared, bridge opened"},
            {"time": "T+5 min", "event": "On-call engineer joined"},
            {"time": "T+10 min", "event": "Service owner paged and joined"},
            {"time": "T+15 min", "event": "Vendor support engaged"},
        ],
        paging_chronology=[
            {"time": "T+0 min", "target": "Primary on-call", "method": "PagerDuty"},
            {"time": "T+5 min", "target": "Secondary on-call", "method": "PagerDuty"},
            {"time": "T+10 min", "target": "Service owner", "method": "Phone"},
        ],
        actions_taken=[
            {"time": "T+5 min", "action": "Initial triage and impact assessment"},
            {"time": "T+15 min", "action": "Root cause identified — configuration rollback initiated"},
            {"time": "T+25 min", "action": "Rollback completed, services recovering"},
            {"time": "T+35 min", "action": "Full service restoration confirmed"},
        ],
        problem_ticket=problem_ticket,
        generated_at=datetime.utcnow(),
    )

    _resolution_store[incident_number] = summary
    logger.info("Resolution summary generated for %s (problem: %s)", incident_number, problem_ticket)
    return summary


def get_resolution(incident_number: str) -> ResolutionSummary | None:
    """Retrieve a previously generated resolution summary."""
    return _resolution_store.get(incident_number)


def post_to_confluence(
    incident_number: str,
    summary: ResolutionSummary | None = None,
) -> str:
    """Stub: post resolution artefacts to Confluence.

    Returns a mock Confluence page URL. In production, this would call
    the Confluence REST API to create a page.
    """
    if summary is None:
        summary = _resolution_store.get(incident_number)
    if summary is None:
        return ""

    # Simulated Confluence URL
    page_id = uuid.uuid4().hex[:8]
    url = f"https://confluence.example.com/wiki/spaces/INC/pages/{page_id}/{incident_number}-PIR"
    summary.confluence_url = url

    logger.info("Resolution posted to Confluence for %s: %s", incident_number, url)
    return url


async def resolve_incident_in_servicenow(
    client: ServiceNowClient,
    incident_sys_id: str,
    resolution_notes: str,
    close_code: str = "Solved (Permanently)",
) -> bool:
    """PATCH the incident in ServiceNow to mark it as resolved.

    Sets state=6 (Resolved), close_code, and close_notes.
    """
    log = get_logger(__name__, incident_sys_id)

    try:
        response = await client.patch(
            f"/api/now/table/incident/{incident_sys_id}",
            json_body={
                "state": "6",
                "close_code": close_code,
                "close_notes": resolution_notes,
            },
        )

        if response.status_code >= 400:
            log.error("Failed to resolve incident — HTTP %s", response.status_code)
            return False

        log.info("Incident %s resolved in ServiceNow", incident_sys_id)
        return True

    except (ServiceNowAPIError, Exception) as exc:
        log.error("Error resolving incident %s: %s", incident_sys_id, exc)
        return False
