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
    extracts key information from the transcript and produces a structured
    summary.

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

    # Extract key lines from transcript for summary
    lines = [l.strip() for l in transcript.strip().splitlines() if l.strip()]
    total_lines = len(lines)

    # Build summary from transcript content
    if total_lines > 0:
        # Use first few lines as context, last lines as resolution
        intro = " ".join(lines[:min(3, total_lines)])
        conclusion = " ".join(lines[max(0, total_lines - 2):])
        summary_text = (
            f"Incident {incident_number} — {description}\n\n"
            f"Meeting Transcript Summary ({total_lines} lines analyzed):\n"
            f"{intro}\n\n"
            f"Resolution: {conclusion}\n\n"
            f"A problem ticket ({problem_ticket}) has been raised for permanent resolution."
        )
        root_cause_text = (
            f"Based on the transcript ({total_lines} lines), the root cause was discussed. "
            f"Key finding: {lines[min(2, total_lines - 1)] if total_lines > 2 else lines[0]}"
        )
        # Extract time-stamped actions if transcript has timestamps
        actions = []
        for line in lines:
            if any(marker in line.lower() for marker in ["t+", "action:", "fix:", "resolved", "identified", "deployed", "rolled back", "escalat"]):
                actions.append({"time": "Meeting", "action": line[:120]})
        if not actions:
            # Create actions from transcript sections
            chunk_size = max(1, total_lines // 4)
            for i in range(0, min(total_lines, 4 * chunk_size), chunk_size):
                actions.append({
                    "time": f"T+{i * 5} min",
                    "action": lines[i][:120] if i < total_lines else "Continued discussion",
                })
    else:
        summary_text = (
            f"Incident {incident_number} — {description}\n\n"
            "Root cause was identified and a fix has been applied. "
            "Services have been restored to normal operation."
        )
        root_cause_text = (
            "A configuration change impacted service availability. "
            "The change was rolled back and services recovered."
        )
        actions = [
            {"time": "T+0 min", "action": "Incident declared, bridge opened"},
            {"time": "T+5 min", "action": "Initial triage and impact assessment"},
            {"time": "T+15 min", "action": "Root cause identified"},
            {"time": "T+25 min", "action": "Fix applied, services recovering"},
        ]

    summary = ResolutionSummary(
        summary=summary_text,
        root_cause=root_cause_text,
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
        actions_taken=actions,
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
