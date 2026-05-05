"""
Dashboard API routes — FastAPI router providing REST endpoints for the
Incident Manager Dashboard.

Each endpoint group corresponds to a React panel component:
- /incidents/{number}/sla          → SLAClockPanel
- /incidents/{number}/stakeholders → StakeholdersPanel
- /incidents/{number}/comms        → CommunicationPanel
- /incidents/{number}/notes        → NotesPanel (Notes tab)
- /incidents/{number}/actions      → NotesPanel (Action Items tab)
- /incidents/{number}/changes      → NotesPanel (Changes tab)
- /incidents/{number}/oncall       → OnCallPanel
- /incidents/{number}/vendor       → VendorPanel
- /incidents/{number}/priority     → PriorityTracker
- /incidents/{number}/handover     → HandoverPanel + ChecklistModal
- /incidents/{number}/resolution   → IncidentResolutionModal
- /incidents/{number}/dashboard    → Full aggregate payload
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from models.dashboard_schemas import (
    ActionItemCreate,
    ActionItemUpdate,
    CommunicationCreate,
    CommunicationType,
    DashboardData,
    HandoverRequest,
    IncidentDetail,
    InfraChangeCreate,
    NoteCreate,
    OnCallTeam,
    ResolutionRequest,
    SLAClockCreate,
    SLAStatus,
    StakeholderCreate,
    VendorInfo,
)
from services import (
    communication_service,
    handover_service,
    notes_service,
    priority_service,
    resolution_service,
    sla_service,
    stakeholder_service,
    vendor_service,
)
from services.incident_service import fetch_incident
from services.oncall_service import fetch_oncall_details
from utils.api_client import ServiceNowClient
from utils.logger import get_logger

router = APIRouter(prefix="/incidents", tags=["dashboard"])
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helper: fetch incident detail from ServiceNow
# ---------------------------------------------------------------------------

async def _get_incident_detail(incident_number: str) -> IncidentDetail:
    """Fetch full incident record from SN and map to IncidentDetail."""
    async with ServiceNowClient() as client:
        response = await client.get(
            "/api/now/table/incident",
            params={
                "sysparm_query": f"number={incident_number}",
                "sysparm_fields": (
                    "sys_id,number,priority,state,short_description,description,"
                    "cmdb_ci,service_offering,assignment_group,assigned_to,"
                    "opened_at,business_impact"
                ),
                "sysparm_display_value": "all",
                "sysparm_limit": "1",
            },
        )
        results = response.json().get("result", [])
        if not results:
            raise HTTPException(status_code=404, detail=f"Incident {incident_number} not found")

        r = results[0]

        def _dv(field: object) -> str | None:
            """Extract display_value from a SN field."""
            if isinstance(field, dict):
                return field.get("display_value") or field.get("value") or None
            return field if isinstance(field, str) and field.strip() else None

        def _val(field: object) -> str | None:
            if isinstance(field, dict):
                return field.get("value") or None
            return field if isinstance(field, str) and field.strip() else None

        return IncidentDetail(
            sys_id=_val(r.get("sys_id")) or "",
            number=_dv(r.get("number")) or incident_number,
            priority=_val(r.get("priority")) or "4",
            state=_map_state(_val(r.get("state"))),
            short_description=_dv(r.get("short_description")) or "",
            description=_dv(r.get("description")) or "",
            cmdb_ci=_val(r.get("cmdb_ci")),
            ci_name=_dv(r.get("cmdb_ci")),
            service_offering=_dv(r.get("service_offering")),
            assignment_group=_dv(r.get("assignment_group")),
            assigned_to=_dv(r.get("assigned_to")),
            business_impact=_dv(r.get("business_impact")),
        )


def _map_state(sn_state: str | None) -> str:
    """Map ServiceNow numeric state to our enum value."""
    mapping = {"1": "new", "2": "in_progress", "3": "on_hold", "6": "resolved", "7": "closed"}
    return mapping.get(sn_state or "", "new")


# ---------------------------------------------------------------------------
# Incident detail
# ---------------------------------------------------------------------------

@router.get("/{incident_number}", response_model=IncidentDetail)
async def get_incident(incident_number: str) -> IncidentDetail:
    """Fetch incident details from ServiceNow."""
    return await _get_incident_detail(incident_number)


# ---------------------------------------------------------------------------
# SLA Clocks
# ---------------------------------------------------------------------------

@router.get("/{incident_number}/sla")
def list_sla_clocks(incident_number: str):
    """Get all SLA clocks for an incident."""
    return sla_service.get_clocks(incident_number)


@router.post("/{incident_number}/sla", status_code=201)
def create_sla_clock(incident_number: str, payload: SLAClockCreate):
    """Add a new SLA clock."""
    return sla_service.add_clock(incident_number, payload)


@router.patch("/{incident_number}/sla/{clock_id}")
def update_sla_clock(incident_number: str, clock_id: str, status: SLAStatus):
    """Pause, resume, or stop a clock."""
    clock = sla_service.update_clock_status(incident_number, clock_id, status)
    if not clock:
        raise HTTPException(status_code=404, detail="Clock not found")
    return clock


@router.delete("/{incident_number}/sla/{clock_id}", status_code=204)
def delete_sla_clock(incident_number: str, clock_id: str):
    """Delete an SLA clock."""
    if not sla_service.delete_clock(incident_number, clock_id):
        raise HTTPException(status_code=404, detail="Clock not found")


@router.post("/{incident_number}/sla/tick")
def tick_sla_clocks(incident_number: str, seconds: int = 1):
    """Advance all running clocks by N seconds. Used for real-time sync."""
    return sla_service.tick_clocks(incident_number, seconds)


# ---------------------------------------------------------------------------
# Stakeholders
# ---------------------------------------------------------------------------

@router.get("/{incident_number}/stakeholders")
def list_stakeholders(incident_number: str):
    """Get all stakeholders for an incident."""
    return stakeholder_service.get_stakeholders(incident_number)


@router.post("/{incident_number}/stakeholders", status_code=201)
def add_stakeholder(incident_number: str, payload: StakeholderCreate):
    """Add a stakeholder to an incident."""
    return stakeholder_service.add_stakeholder(incident_number, payload)


@router.delete("/{incident_number}/stakeholders/{stakeholder_id}", status_code=204)
def remove_stakeholder(incident_number: str, stakeholder_id: str):
    """Remove a stakeholder."""
    if not stakeholder_service.remove_stakeholder(incident_number, stakeholder_id):
        raise HTTPException(status_code=404, detail="Stakeholder not found")


# ---------------------------------------------------------------------------
# Communications
# ---------------------------------------------------------------------------

@router.get("/{incident_number}/comms")
def list_communications(incident_number: str):
    """Get all communications for an incident."""
    return communication_service.get_communications(incident_number)


@router.post("/{incident_number}/comms", status_code=201)
def send_communication(incident_number: str, payload: CommunicationCreate):
    """Record and send a communication."""
    return communication_service.add_communication(incident_number, payload)


@router.get("/{incident_number}/comms/template")
async def get_comm_template(incident_number: str, comm_type: CommunicationType):
    """Render an email template with incident context."""
    incident = await _get_incident_detail(incident_number)
    context = {
        "number": incident.number,
        "priority": f"P{incident.priority}",
        "state": incident.state,
        "description": incident.short_description,
        "business_impact": incident.business_impact or "Unknown",
    }
    return communication_service.render_template(comm_type, context)


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

@router.get("/{incident_number}/notes")
def list_notes(incident_number: str):
    """Get all notes for an incident."""
    return notes_service.get_notes(incident_number)


@router.post("/{incident_number}/notes", status_code=201)
def add_note(incident_number: str, payload: NoteCreate):
    """Add a note."""
    return notes_service.add_note(incident_number, payload)


@router.delete("/{incident_number}/notes/{note_id}", status_code=204)
def delete_note(incident_number: str, note_id: str):
    """Delete a note."""
    if not notes_service.delete_note(incident_number, note_id):
        raise HTTPException(status_code=404, detail="Note not found")


# ---------------------------------------------------------------------------
# Action Items
# ---------------------------------------------------------------------------

@router.get("/{incident_number}/actions")
def list_action_items(incident_number: str):
    """Get all action items for an incident."""
    return notes_service.get_action_items(incident_number)


@router.post("/{incident_number}/actions", status_code=201)
def add_action_item(incident_number: str, payload: ActionItemCreate):
    """Create an action item."""
    return notes_service.add_action_item(incident_number, payload)


@router.patch("/{incident_number}/actions/{item_id}")
def update_action_item(incident_number: str, item_id: str, payload: ActionItemUpdate):
    """Update an action item (status, assignee, due date)."""
    item = notes_service.update_action_item(incident_number, item_id, payload)
    if not item:
        raise HTTPException(status_code=404, detail="Action item not found")
    return item


@router.delete("/{incident_number}/actions/{item_id}", status_code=204)
def delete_action_item(incident_number: str, item_id: str):
    """Delete an action item."""
    if not notes_service.delete_action_item(incident_number, item_id):
        raise HTTPException(status_code=404, detail="Action item not found")


# ---------------------------------------------------------------------------
# Infrastructure Changes
# ---------------------------------------------------------------------------

@router.get("/{incident_number}/changes")
def list_changes(incident_number: str):
    """Get all infrastructure changes for an incident."""
    return notes_service.get_changes(incident_number)


@router.post("/{incident_number}/changes", status_code=201)
def add_change(incident_number: str, payload: InfraChangeCreate):
    """Record an infrastructure change."""
    return notes_service.add_change(incident_number, payload)


@router.delete("/{incident_number}/changes/{change_id}", status_code=204)
def delete_change(incident_number: str, change_id: str):
    """Delete an infrastructure change record."""
    if not notes_service.delete_change(incident_number, change_id):
        raise HTTPException(status_code=404, detail="Change not found")


# ---------------------------------------------------------------------------
# On-Call Teams
# ---------------------------------------------------------------------------

@router.get("/{incident_number}/oncall")
async def list_oncall_teams(incident_number: str):
    """Fetch on-call teams from ServiceNow for the incident's assignment group."""
    incident = await _get_incident_detail(incident_number)
    if not incident.assignment_group:
        return []

    try:
        async with ServiceNowClient() as client:
            oncall = await fetch_oncall_details(
                client, incident.assignment_group, incident_number
            )
            return oncall
    except Exception as exc:
        logger.error("On-call fetch failed for %s: %s", incident_number, exc)
        return []


# ---------------------------------------------------------------------------
# Vendor
# ---------------------------------------------------------------------------

@router.get("/{incident_number}/vendor")
def get_vendor(incident_number: str):
    """Get vendor info for an incident."""
    return vendor_service.get_vendor_info(incident_number)


@router.put("/{incident_number}/vendor")
def update_vendor(incident_number: str, payload: VendorInfo):
    """Set or update vendor info."""
    return vendor_service.set_vendor_info(incident_number, payload)


# ---------------------------------------------------------------------------
# Priority History
# ---------------------------------------------------------------------------

@router.get("/{incident_number}/priority")
async def get_priority_history(incident_number: str):
    """Fetch priority change history from ServiceNow audit trail."""
    # Try local cache first
    local = priority_service.get_priority_history(incident_number)
    if local:
        return local

    # Fetch from ServiceNow
    incident = await _get_incident_detail(incident_number)
    async with ServiceNowClient() as client:
        return await priority_service.fetch_priority_history_from_sn(
            client, incident.sys_id, incident_number
        )


@router.post("/{incident_number}/priority")
def add_priority_change(
    incident_number: str,
    from_priority: str,
    to_priority: str,
    changed_by: str = "",
    reason: str = "",
):
    """Record a manual priority change."""
    return priority_service.add_priority_change(
        incident_number, from_priority, to_priority, changed_by, reason
    )


# ---------------------------------------------------------------------------
# Handover
# ---------------------------------------------------------------------------

@router.get("/{incident_number}/handover")
def get_handover_info(incident_number: str):
    """Get current owner and handover history."""
    return {
        "current_owner": handover_service.get_current_owner(incident_number),
        "history": handover_service.get_handover_history(incident_number),
    }


@router.post("/{incident_number}/handover")
def transfer_ownership(incident_number: str, payload: HandoverRequest):
    """Execute a shift handover (requires complete checklist)."""
    record = handover_service.transfer_ownership(incident_number, payload)
    if record is None:
        incomplete = handover_service.validate_checklist(payload.checklist)
        raise HTTPException(
            status_code=400,
            detail=f"Handover blocked — incomplete items: {', '.join(incomplete)}",
        )
    return record


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

@router.get("/{incident_number}/resolution")
def get_resolution(incident_number: str):
    """Get the resolution summary if one exists."""
    summary = resolution_service.get_resolution(incident_number)
    if not summary:
        raise HTTPException(status_code=404, detail="No resolution found")
    return summary


@router.post("/{incident_number}/resolution/generate")
async def generate_resolution_summary(
    incident_number: str,
    transcript: str = "",
    request: Request = None,
):
    """Generate an AI-style resolution summary from a transcript.

    Accepts transcript either as a query param or in the JSON body
    as {"transcript": "..."}.
    """
    # Prefer body content over query param
    if request:
        try:
            body = await request.json()
            if body.get("transcript"):
                transcript = body["transcript"]
        except Exception:
            pass
    return resolution_service.generate_summary(incident_number, transcript)


@router.post("/{incident_number}/resolution/publish")
def publish_to_confluence(incident_number: str):
    """Post the resolution summary to Confluence."""
    url = resolution_service.post_to_confluence(incident_number)
    if not url:
        raise HTTPException(status_code=404, detail="No resolution to publish")
    return {"confluence_url": url}


@router.post("/{incident_number}/resolve")
async def resolve_incident(incident_number: str, payload: ResolutionRequest):
    """Resolve the incident in ServiceNow."""
    incident = await _get_incident_detail(incident_number)
    async with ServiceNowClient() as client:
        success = await resolution_service.resolve_incident_in_servicenow(
            client,
            incident.sys_id,
            resolution_notes=payload.resolution_notes,
            close_code=payload.close_code or "Solved (Permanently)",
        )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to resolve in ServiceNow")
    return {"status": "resolved", "incident": incident_number}


# ---------------------------------------------------------------------------
# Full Dashboard aggregate
# ---------------------------------------------------------------------------

@router.get("/{incident_number}/dashboard", response_model=DashboardData)
async def get_dashboard(incident_number: str):
    """Return the full dashboard payload for a single incident.

    Aggregates data from all services into a single response matching
    what the React App.tsx component needs to render the full UI.
    """
    incident = await _get_incident_detail(incident_number)

    # Fetch priority history from SN
    priority_history = []
    try:
        async with ServiceNowClient() as client:
            priority_history = await priority_service.fetch_priority_history_from_sn(
                client, incident.sys_id, incident_number
            )
    except Exception:
        priority_history = priority_service.get_priority_history(incident_number)

    return DashboardData(
        incident=incident,
        sla_clocks=sla_service.get_clocks(incident_number),
        stakeholders=stakeholder_service.get_stakeholders(incident_number),
        communications=communication_service.get_communications(incident_number),
        notes=notes_service.get_notes(incident_number),
        action_items=notes_service.get_action_items(incident_number),
        changes=notes_service.get_changes(incident_number),
        vendor_info=vendor_service.get_vendor_info(incident_number),
        priority_history=priority_history,
        handovers=handover_service.get_handover_history(incident_number),
        resolution=resolution_service.get_resolution(incident_number),
    )
