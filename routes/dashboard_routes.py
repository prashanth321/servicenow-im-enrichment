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

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

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
from services.auth_service import get_current_user
from utils.api_client import ServiceNowClient, sanitize_sysparm
from utils.logger import get_logger
from utils.sn_fields import extract_display, extract_value

router = APIRouter(
    prefix="/incidents",
    tags=["dashboard"],
    dependencies=[Depends(get_current_user)],
)
logger = get_logger(__name__)

_CONTACTS_FILE = Path(__file__).resolve().parent.parent / "config" / "contacts.json"


def _load_contacts() -> dict:
    """Load the contacts configuration file."""
    try:
        return json.loads(_CONTACTS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"distribution_lists": [], "contacts": []}


# ---------------------------------------------------------------------------
# Helper: fetch incident detail from ServiceNow
# ---------------------------------------------------------------------------

async def _get_incident_detail(incident_number: str) -> IncidentDetail:
    """Fetch full incident record from SN and map to IncidentDetail."""
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
            raise HTTPException(status_code=404, detail=f"Incident {incident_number} not found")

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
            major_incident_manager=_dv(r.get("u_major_incident_manager")),
            business_impact=_dv(r.get("business_impact")),
        )


def _map_state(sn_state: str | None) -> str:
    """Map ServiceNow numeric state to our enum value."""
    mapping = {"1": "new", "2": "in_progress", "3": "on_hold", "6": "resolved", "7": "closed"}
    return mapping.get(sn_state or "", "new")


# ---------------------------------------------------------------------------
# Auto-sync helper — pushes dashboard state to ServiceNow work_notes
# ---------------------------------------------------------------------------

async def _auto_sync_to_servicenow(incident_number: str, latest_entry: str = "") -> None:
    """Automatically sync the latest dashboard update to ServiceNow work_notes.

    Called after any mutation (add/update/delete) to action items, notes, or changes.
    Only sends the latest change, not all accumulated data.
    Failures are logged but do not block the response.
    """

    try:
        incident = await _get_incident_detail(incident_number)

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
async def send_communication(incident_number: str, payload: CommunicationCreate):
    """Record and send a communication."""
    return await communication_service.add_communication(incident_number, payload)


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
    """Get all notes for an incident (local + ServiceNow work_notes)."""
    return notes_service.get_notes(incident_number)


@router.get("/{incident_number}/notes/servicenow")
async def get_servicenow_notes(incident_number: str):
    """Fetch work_notes and comments from the ServiceNow incident journal."""
    try:
        incident = await _get_incident_detail(incident_number)
        sn_notes = []
        async with ServiceNowClient() as client:
            # Fetch work_notes (internal journal entries)
            resp = await client.get(
                "/api/now/table/sys_journal_field",
                params={
                    "sysparm_query": f"element_id={incident.sys_id}^element=work_notes^ORDERBYDESCsys_created_on",
                    "sysparm_fields": "value,sys_created_on,sys_created_by",
                    "sysparm_limit": "50",
                },
            )
            work_notes = resp.json().get("result", [])
            for entry in work_notes:
                sn_notes.append({
                    "id": f"sn_wn_{entry.get('sys_created_on', '')}",
                    "content": entry.get("value", ""),
                    "author": entry.get("sys_created_by", "System"),
                    "created_at": entry.get("sys_created_on", ""),
                    "source": "work_notes",
                })

            # Fetch comments (customer-visible)
            resp2 = await client.get(
                "/api/now/table/sys_journal_field",
                params={
                    "sysparm_query": f"element_id={incident.sys_id}^element=comments^ORDERBYDESCsys_created_on",
                    "sysparm_fields": "value,sys_created_on,sys_created_by",
                    "sysparm_limit": "50",
                },
            )
            comments = resp2.json().get("result", [])
            for entry in comments:
                sn_notes.append({
                    "id": f"sn_cm_{entry.get('sys_created_on', '')}",
                    "content": entry.get("value", ""),
                    "author": entry.get("sys_created_by", "System"),
                    "created_at": entry.get("sys_created_on", ""),
                    "source": "comments",
                })

        # Sort combined by created_at descending
        sn_notes.sort(key=lambda x: x["created_at"], reverse=True)
        return sn_notes
    except Exception as e:
        logger.warning("Failed to fetch SN notes for %s: %s", incident_number, e)
        return []


@router.post("/{incident_number}/notes", status_code=201)
async def add_note(incident_number: str, payload: NoteCreate):
    """Add a note and sync to ServiceNow."""
    note = notes_service.add_note(incident_number, payload)
    await _auto_sync_to_servicenow(incident_number, f"[Note Added] {payload.author or 'Unknown'}: {payload.content}")
    return note


@router.delete("/{incident_number}/notes/{note_id}", status_code=204)
async def delete_note(incident_number: str, note_id: str):
    """Delete a note and sync to ServiceNow."""
    if not notes_service.delete_note(incident_number, note_id):
        raise HTTPException(status_code=404, detail="Note not found")
    await _auto_sync_to_servicenow(incident_number, "[Note Deleted]")


# ---------------------------------------------------------------------------
# Action Items
# ---------------------------------------------------------------------------

@router.get("/{incident_number}/actions")
def list_action_items(incident_number: str):
    """Get all action items for an incident."""
    return notes_service.get_action_items(incident_number)


@router.post("/{incident_number}/actions", status_code=201)
async def add_action_item(incident_number: str, payload: ActionItemCreate):
    """Create an action item and sync to ServiceNow."""
    item = notes_service.add_action_item(incident_number, payload)
    await _auto_sync_to_servicenow(incident_number, f"[Action Added] {payload.description} | Team: {payload.team or 'N/A'} | Assignee: {payload.assignee or 'Unassigned'}")
    return item


@router.patch("/{incident_number}/actions/{item_id}")
async def update_action_item(incident_number: str, item_id: str, payload: ActionItemUpdate):
    """Update an action item (status, assignee, due date) and sync to ServiceNow."""
    item = notes_service.update_action_item(incident_number, item_id, payload)
    if not item:
        raise HTTPException(status_code=404, detail="Action item not found")
    await _auto_sync_to_servicenow(incident_number, f"[Action Updated] {item.description} | Status: {item.status.value}")
    return item


@router.delete("/{incident_number}/actions/{item_id}", status_code=204)
async def delete_action_item(incident_number: str, item_id: str):
    """Delete an action item and sync to ServiceNow."""
    if not notes_service.delete_action_item(incident_number, item_id):
        raise HTTPException(status_code=404, detail="Action item not found")
    await _auto_sync_to_servicenow(incident_number, "[Action Item Deleted]")


# ---------------------------------------------------------------------------
# Infrastructure Changes
# ---------------------------------------------------------------------------

@router.get("/{incident_number}/changes")
def list_changes(incident_number: str):
    """Get all infrastructure changes for an incident."""
    return notes_service.get_changes(incident_number)


@router.get("/{incident_number}/changes/scheduled")
async def list_scheduled_changes(incident_number: str):
    """Fetch scheduled change requests from ServiceNow during the incident window."""
    try:
        incident = await _get_incident_detail(incident_number)
        opened_at = incident.opened_at
        if not opened_at:
            return []

        # Format the date for ServiceNow query
        if isinstance(opened_at, str):
            sn_date = opened_at
        else:
            sn_date = opened_at.strftime("%Y-%m-%d %H:%M:%S")

        async with ServiceNowClient() as client:
            # Query change_request table for changes scheduled around the incident time
            # Look for changes that overlap with the incident window
            resp = await client.get(
                "/api/now/table/change_request",
                params={
                    "sysparm_query": (
                        f"start_date<={sn_date}"
                        f"^end_date>={sn_date}"
                        f"^ORstart_date>={sn_date}"
                        "^stateIN-1,1,2,3"
                        "^ORDERBYDESCstart_date"
                    ),
                    "sysparm_fields": (
                        "number,short_description,state,start_date,end_date,"
                        "assignment_group,assigned_to,cmdb_ci,category,type,risk"
                    ),
                    "sysparm_display_value": "true",
                    "sysparm_limit": "20",
                },
            )
            results = resp.json().get("result", [])
            changes = []
            for r in results:
                changes.append({
                    "number": r.get("number", ""),
                    "short_description": r.get("short_description", ""),
                    "state": r.get("state", ""),
                    "start_date": r.get("start_date", ""),
                    "end_date": r.get("end_date", ""),
                    "assignment_group": r.get("assignment_group", ""),
                    "assigned_to": r.get("assigned_to", ""),
                    "cmdb_ci": r.get("cmdb_ci", ""),
                    "category": r.get("category", ""),
                    "type": r.get("type", ""),
                    "risk": r.get("risk", ""),
                })
            return changes
    except Exception as e:
        logger.warning("Failed to fetch scheduled changes for %s: %s", incident_number, e)
        return []


@router.post("/{incident_number}/changes", status_code=201)
async def add_change(incident_number: str, payload: InfraChangeCreate):
    """Record an infrastructure change and sync to ServiceNow."""
    change = notes_service.add_change(incident_number, payload)
    await _auto_sync_to_servicenow(incident_number, f"[Change Recorded] {payload.description} | Owner: {payload.owner_team or 'N/A'}")
    return change


@router.delete("/{incident_number}/changes/{change_id}", status_code=204)
async def delete_change(incident_number: str, change_id: str):
    """Delete an infrastructure change record and sync to ServiceNow."""
    if not notes_service.delete_change(incident_number, change_id):
        raise HTTPException(status_code=404, detail="Change not found")
    await _auto_sync_to_servicenow(incident_number, "[Change Record Deleted]")


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
async def get_vendor(incident_number: str):
    """Get vendor info for an incident, fetched fresh from ServiceNow."""
    try:
        incident = await _get_incident_detail(incident_number)
        async with ServiceNowClient() as client:
            vendor = await vendor_service.lookup_vendor_for_incident(
                client, incident_number, incident.cmdb_ci, incident.assignment_group,
            )
            if vendor:
                return vendor
    except Exception:
        logger.warning("Failed to fetch vendor from SN for %s, using cached/default", incident_number)

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
async def transfer_ownership(incident_number: str, payload: HandoverRequest):
    """Execute a shift handover (requires complete checklist and valid SN user)."""
    # Validate user exists in ServiceNow
    target = sanitize_sysparm(payload.target_manager.strip())
    if not target:
        raise HTTPException(status_code=400, detail="Target manager name is required")

    async with ServiceNowClient() as client:
        resp = await client.get(
            "/api/now/table/sys_user",
            params={
                "sysparm_query": f"name={target}^active=true",
                "sysparm_fields": "sys_id,name,email,title",
                "sysparm_limit": "1",
            },
        )
        users = resp.json().get("result", [])
        if not users:
            raise HTTPException(
                status_code=404,
                detail=f"User '{target}' not found in ServiceNow. Please enter a valid user name.",
            )

        sn_user = users[0]
        validated_name = sn_user.get("name", target)

    # Perform the handover with the validated name
    payload.target_manager = validated_name
    record = handover_service.transfer_ownership(incident_number, payload)
    if record is None:
        incomplete = handover_service.validate_checklist(payload.checklist)
        raise HTTPException(
            status_code=400,
            detail=f"Handover blocked — incomplete items: {', '.join(incomplete)}",
        )

    # Update assigned_to in ServiceNow
    try:
        incident = await _get_incident_detail(incident_number)
        if incident.sys_id:
            async with ServiceNowClient() as client:
                await client.patch(
                    f"/api/now/table/incident/{incident.sys_id}",
                    json_body={
                        "assigned_to": sn_user["sys_id"],
                        "work_notes": f"[IM Dashboard] Shift handover: assigned to {validated_name}",
                    },
                )
                logger.info("Incident %s reassigned to %s in ServiceNow", incident_number, validated_name)
    except Exception as exc:
        logger.warning("Failed to update assigned_to in SN for %s: %s", incident_number, exc)

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
    if not payload.resolution_notes or not payload.resolution_notes.strip():
        raise HTTPException(status_code=400, detail="Resolution notes are required")

    incident = await _get_incident_detail(incident_number)
    if not incident.sys_id:
        raise HTTPException(status_code=400, detail="Could not find sys_id for incident")

    logger.info("Resolving incident %s (sys_id=%s)", incident_number, incident.sys_id)

    async with ServiceNowClient() as client:
        success = await resolution_service.resolve_incident_in_servicenow(
            client,
            incident.sys_id,
            resolution_notes=payload.resolution_notes,
            close_code=payload.close_code or "Solved (Permanently)",
        )

        if not success:
            logger.error("Resolve failed for %s (sys_id=%s)", incident_number, incident.sys_id)
            raise HTTPException(
                status_code=500,
                detail=(
                    "Failed to resolve in ServiceNow. The incident state was not updated. "
                    "Check that the incident is not already resolved/closed, and that "
                    "mandatory fields (caller, assignment group) are populated in ServiceNow."
                ),
            )

        # Also add resolution notes as a work_note for audit trail
        try:
            await client.patch(
                f"/api/now/table/incident/{incident.sys_id}",
                json_body={
                    "work_notes": f"[IM Dashboard Resolution]\n{payload.resolution_notes}",
                },
            )
        except Exception:
            logger.warning("Failed to add resolution work_note for %s", incident_number)

    # Auto-generate a basic resolution record if one doesn't exist
    if not resolution_service.get_resolution(incident_number):
        resolution_service.generate_summary(
            incident_number,
            payload.resolution_notes,
            {"short_description": incident.short_description},
        )

    return {"status": "resolved", "incident": incident_number}


# ---------------------------------------------------------------------------
# Sync dashboard actions to ServiceNow work_notes
# ---------------------------------------------------------------------------

@router.post("/{incident_number}/sync")
async def sync_actions_to_servicenow(incident_number: str):
    """Push all dashboard actions, notes, and changes to the incident work_notes.

    Builds a formatted work_notes entry from the current dashboard state
    and PATCHes it onto the ServiceNow incident record.
    """
    incident = await _get_incident_detail(incident_number)

    # Gather dashboard data
    actions = notes_service.get_action_items(incident_number)
    notes = notes_service.get_notes(incident_number)
    changes = notes_service.get_changes(incident_number)

    # Build work_notes content
    lines: list[str] = ["=== IM Dashboard Sync ==="]
    lines.append(f"Incident: {incident_number}")
    lines.append(f"Synced at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append("")

    if actions:
        lines.append("--- Action Items ---")
        for a in actions:
            status = "✓" if a.status.value == "completed" else "○"
            lines.append(f"  {status} {a.description} | Team: {a.team or 'N/A'} | Assignee: {a.assignee or 'Unassigned'} | Status: {a.status.value}")
        lines.append("")

    if notes:
        lines.append("--- Notes ---")
        for n in notes:
            ts = n.created_at.strftime('%H:%M') if n.created_at else ''
            lines.append(f"  [{ts}] {n.author or 'Unknown'}: {n.content}")
        lines.append("")

    if changes:
        lines.append("--- Infrastructure Changes ---")
        for c in changes:
            lines.append(f"  • {c.description} | Owner: {c.owner_team or 'N/A'} | Assignee: {c.assignee or 'N/A'}")
        lines.append("")

    lines.append("=== End Dashboard Sync ===")
    work_notes = "\n".join(lines)

    # PATCH the incident
    async with ServiceNowClient() as client:
        response = await client.patch(
            f"/api/now/table/incident/{incident.sys_id}",
            json_body={"work_notes": work_notes},
        )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to sync to ServiceNow — HTTP {response.status_code}",
            )

    logger.info("Dashboard actions synced to incident %s", incident_number)
    return {
        "status": "synced",
        "incident": incident_number,
        "actions_count": len(actions),
        "notes_count": len(notes),
        "changes_count": len(changes),
    }


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

    # Fetch priority history and vendor info from SN
    priority_history = []
    vendor_info = None
    try:
        async with ServiceNowClient() as client:
            priority_history = await priority_service.fetch_priority_history_from_sn(
                client, incident.sys_id, incident_number
            )

            vendor_info = await vendor_service.lookup_vendor_for_incident(
                client, incident_number, incident.cmdb_ci, incident.assignment_group,
            )
    except Exception:
        priority_history = priority_service.get_priority_history(incident_number)

    if vendor_info is None:
        vendor_info = vendor_service.get_vendor_info(incident_number)

    return DashboardData(
        incident=incident,
        sla_clocks=sla_service.get_clocks(incident_number),
        stakeholders=stakeholder_service.get_stakeholders(incident_number),
        communications=communication_service.get_communications(incident_number),
        notes=notes_service.get_notes(incident_number),
        action_items=notes_service.get_action_items(incident_number),
        changes=notes_service.get_changes(incident_number),
        vendor_info=vendor_info,
        priority_history=priority_history,
        handovers=handover_service.get_handover_history(incident_number),
        resolution=resolution_service.get_resolution(incident_number),
    )
