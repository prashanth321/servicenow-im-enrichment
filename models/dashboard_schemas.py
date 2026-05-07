"""
Pydantic models for the Incident Manager Dashboard.

Covers SLA clocks, stakeholders, communications, notes, action items,
infrastructure changes, on-call teams, vendor info, priority escalation,
shift handover, and incident resolution — converted from the React/TS
front-end components.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Priority(str, Enum):
    P1 = "1"
    P2 = "2"
    P3 = "3"
    P4 = "4"


class IncidentState(str, Enum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    ON_HOLD = "on_hold"
    RESOLVED = "resolved"
    CLOSED = "closed"


class SLAStatus(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    BREACHED = "breached"
    MET = "met"


class ActionItemStatus(str, Enum):
    OPEN = "open"
    COMPLETED = "completed"


class HandoverCheckItem(str, Enum):
    STATUS_REVIEWED = "status_reviewed"
    ACTIONS_TRANSFERRED = "actions_transferred"
    STAKEHOLDER_COMMS_SHARED = "stakeholder_comms_shared"
    VENDOR_STATUS_CONFIRMED = "vendor_status_confirmed"
    ESCALATION_POINTS_IDENTIFIED = "escalation_points_identified"


# ---------------------------------------------------------------------------
# Incident detail (full dashboard view)
# ---------------------------------------------------------------------------

class IncidentDetail(BaseModel):
    """Extended incident data for the dashboard header and context."""

    sys_id: str
    number: str
    priority: Priority
    state: IncidentState = IncidentState.NEW
    short_description: str = ""
    description: str = ""
    cmdb_ci: str | None = None
    ci_name: str | None = None
    service_offering: str | None = None
    assignment_group: str | None = None
    assigned_to: str | None = None
    opened_at: datetime | None = None
    opened_by: str | None = None
    major_incident_manager: str | None = None
    business_impact: str | None = None
    duration_minutes: int | None = None


# ---------------------------------------------------------------------------
# SLA Clocks — mirrors SLAClockPanel.tsx
# ---------------------------------------------------------------------------

class SLAClock(BaseModel):
    """A single SLA countdown clock."""

    id: str = Field(..., description="Unique clock identifier")
    label: str = Field(..., description="Clock label (e.g. 'Customer Update SLA')")
    target_minutes: int = Field(..., description="Target duration in minutes")
    remaining_seconds: int = Field(..., description="Seconds remaining (negative = breached)")
    status: SLAStatus = SLAStatus.RUNNING
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SLAClockCreate(BaseModel):
    """Payload to create a new SLA clock."""

    label: str
    target_minutes: int


class SLAClockUpdate(BaseModel):
    """Payload to pause/resume/stop a clock."""

    status: SLAStatus


# ---------------------------------------------------------------------------
# Stakeholders — mirrors StakeholdersPanel.tsx
# ---------------------------------------------------------------------------

class Stakeholder(BaseModel):
    """A stakeholder involved in the incident."""

    id: str = Field(default="", description="Unique identifier")
    name: str
    role: str = ""
    team: str = ""
    email: str | None = None
    phone: str | None = None


class StakeholderCreate(BaseModel):
    name: str
    role: str = ""
    team: str = ""
    email: str | None = None
    phone: str | None = None


# ---------------------------------------------------------------------------
# Communication — mirrors CommunicationPanel.tsx / CommunicationModal
# ---------------------------------------------------------------------------

class CommunicationType(str, Enum):
    STATUS_UPDATE = "status_update"
    CUSTOMER_IMPACT = "customer_impact"
    RESOLUTION_NOTICE = "resolution_notice"
    ESCALATION = "escalation"


class Communication(BaseModel):
    """A communication record (sent update)."""

    id: str = ""
    incident_number: str = ""
    comm_type: CommunicationType = CommunicationType.STATUS_UPDATE
    subject: str = ""
    body: str = ""
    recipients: list[str] = Field(default_factory=list)
    sent_at: datetime = Field(default_factory=datetime.utcnow)
    sent_by: str = ""


class CommunicationCreate(BaseModel):
    """Payload to send a new communication."""

    comm_type: CommunicationType
    subject: str
    body: str
    recipients: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Notes — mirrors NotesPanel.tsx (Notes tab)
# ---------------------------------------------------------------------------

class Note(BaseModel):
    """A timestamped incident note."""

    id: str = ""
    incident_number: str = ""
    content: str
    author: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class NoteCreate(BaseModel):
    content: str
    author: str = ""


# ---------------------------------------------------------------------------
# Action Items — mirrors NotesPanel.tsx (Action Items tab)
# ---------------------------------------------------------------------------

class ActionItem(BaseModel):
    """An action item assigned during the incident."""

    id: str = ""
    incident_number: str = ""
    description: str
    team: str = ""
    assignee: str = ""
    due_date: datetime | None = None
    status: ActionItemStatus = ActionItemStatus.OPEN
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ActionItemCreate(BaseModel):
    description: str
    team: str = ""
    assignee: str = ""
    due_date: datetime | None = None


class ActionItemUpdate(BaseModel):
    status: ActionItemStatus | None = None
    assignee: str | None = None
    due_date: datetime | None = None


# ---------------------------------------------------------------------------
# Infrastructure Changes — mirrors NotesPanel.tsx (Changes tab)
# ---------------------------------------------------------------------------

class InfraChange(BaseModel):
    """An infrastructure change made during the incident."""

    id: str = ""
    incident_number: str = ""
    description: str
    owner_team: str = ""
    assignee: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class InfraChangeCreate(BaseModel):
    description: str
    owner_team: str = ""
    assignee: str = ""


# ---------------------------------------------------------------------------
# On-Call Teams — mirrors OnCallPanel.tsx
# ---------------------------------------------------------------------------

class OnCallContact(BaseModel):
    """A single on-call contact."""

    name: str
    role: str = ""  # "primary" | "secondary"
    phone: str | None = None
    email: str | None = None


class OnCallTeam(BaseModel):
    """An on-call team with primary/secondary contacts."""

    team_name: str
    category: str = ""  # Infrastructure, Data, Security, Engineering
    primary: OnCallContact | None = None
    secondary: OnCallContact | None = None


class OnCallOverride(BaseModel):
    """Override the primary/secondary for a team."""

    team_name: str
    role: str  # "primary" | "secondary"
    contact_name: str


# ---------------------------------------------------------------------------
# Vendor — mirrors VendorPanel.tsx
# ---------------------------------------------------------------------------

class VendorSupportHours(BaseModel):
    weekday: str = ""
    weekend: str = ""
    holiday: str = ""
    emergency: str = ""


class VendorSLA(BaseModel):
    priority: str = ""
    response_time: str = ""
    resolution_time: str = ""


class VendorInfo(BaseModel):
    """Vendor contact and SLA information."""

    vendor_name: str
    account_manager: str | None = None
    support_email: str | None = None
    support_phone: str | None = None
    emergency_line: str | None = None
    support_hours: VendorSupportHours | None = None
    sla_terms: list[VendorSLA] = Field(default_factory=list)
    uptime_guarantee: str | None = None
    contract_expiry: str | None = None


# ---------------------------------------------------------------------------
# Priority Tracker — mirrors PriorityTracker.tsx
# ---------------------------------------------------------------------------

class PriorityChange(BaseModel):
    """A single priority escalation/de-escalation event."""

    from_priority: str
    to_priority: str
    changed_at: datetime
    changed_by: str = ""
    reason: str = ""


# ---------------------------------------------------------------------------
# Handover — mirrors HandoverPanel.tsx / HandoverChecklistModal.tsx
# ---------------------------------------------------------------------------

class HandoverChecklist(BaseModel):
    """Checklist state for shift handover."""

    status_reviewed: bool = False
    actions_transferred: bool = False
    stakeholder_comms_shared: bool = False
    vendor_status_confirmed: bool = False
    escalation_points_identified: bool = False


class HandoverRequest(BaseModel):
    """Request to transfer ownership to another incident manager."""

    target_manager: str
    checklist: HandoverChecklist


class HandoverRecord(BaseModel):
    """Completed handover record."""

    id: str = ""
    incident_number: str = ""
    from_manager: str = ""
    to_manager: str = ""
    checklist: HandoverChecklist = Field(default_factory=HandoverChecklist)
    transferred_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Resolution — mirrors IncidentResolutionModal.tsx
# ---------------------------------------------------------------------------

class ResolutionSummary(BaseModel):
    """AI-generated or manual resolution summary."""

    summary: str = ""
    root_cause: str = ""
    people_chronology: list[dict] = Field(default_factory=list)
    paging_chronology: list[dict] = Field(default_factory=list)
    actions_taken: list[dict] = Field(default_factory=list)
    problem_ticket: str | None = None
    confluence_url: str | None = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ResolutionRequest(BaseModel):
    """Request to resolve an incident."""

    resolution_notes: str = ""
    close_code: str = ""


# ---------------------------------------------------------------------------
# Dashboard aggregate response
# ---------------------------------------------------------------------------

class DashboardData(BaseModel):
    """Full dashboard payload for a single incident."""

    incident: IncidentDetail
    sla_clocks: list[SLAClock] = Field(default_factory=list)
    stakeholders: list[Stakeholder] = Field(default_factory=list)
    communications: list[Communication] = Field(default_factory=list)
    notes: list[Note] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    changes: list[InfraChange] = Field(default_factory=list)
    oncall_teams: list[OnCallTeam] = Field(default_factory=list)
    vendor_info: VendorInfo | None = None
    priority_history: list[PriorityChange] = Field(default_factory=list)
    handovers: list[HandoverRecord] = Field(default_factory=list)
    resolution: ResolutionSummary | None = None
