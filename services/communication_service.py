"""
Communication tracking service.

Records outbound communications (status updates, customer impact notices,
escalations, resolution notices) sent during an incident. Also provides
email template rendering.

Converted from CommunicationPanel.tsx / CommunicationModal.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from models.dashboard_schemas import Communication, CommunicationCreate, CommunicationType
from utils.logger import get_logger

# In-memory store: incident_number -> list[Communication]
_comm_store: dict[str, list[Communication]] = {}

logger = get_logger(__name__)

# Pre-defined email templates matching the React CommunicationModal
_TEMPLATES: dict[CommunicationType, dict[str, str]] = {
    CommunicationType.STATUS_UPDATE: {
        "subject": "[{number}] Status Update — {priority}",
        "body": (
            "Incident: {number}\n"
            "Priority: {priority}\n"
            "Status: {state}\n\n"
            "Current Situation:\n{description}\n\n"
            "Next Steps:\n- Continuing investigation\n"
            "- Next update in 30 minutes\n\n"
            "Regards,\nIncident Management Team"
        ),
    },
    CommunicationType.CUSTOMER_IMPACT: {
        "subject": "[{number}] Customer Impact Notification",
        "body": (
            "We are currently experiencing an issue affecting services.\n\n"
            "Incident: {number}\n"
            "Impact: {business_impact}\n"
            "Description: {description}\n\n"
            "Our team is actively working to resolve this. "
            "We will provide updates every 30 minutes.\n\n"
            "Regards,\nIncident Management Team"
        ),
    },
    CommunicationType.RESOLUTION_NOTICE: {
        "subject": "[{number}] Resolved",
        "body": (
            "Incident {number} has been resolved.\n\n"
            "Resolution Summary:\n{description}\n\n"
            "If you continue to experience issues, please contact the service desk.\n\n"
            "Regards,\nIncident Management Team"
        ),
    },
    CommunicationType.ESCALATION: {
        "subject": "[{number}] Escalation — Immediate Attention Required",
        "body": (
            "This incident requires immediate escalation.\n\n"
            "Incident: {number}\n"
            "Priority: {priority}\n"
            "Description: {description}\n\n"
            "Please join the bridge call immediately.\n\n"
            "Regards,\nIncident Management Team"
        ),
    },
}


def render_template(
    comm_type: CommunicationType,
    incident_context: dict[str, str],
) -> dict[str, str]:
    """Render an email template with incident context variables.

    Args:
        comm_type: The type of communication.
        incident_context: Dict with keys like number, priority, state, description, business_impact.

    Returns:
        Dict with 'subject' and 'body' strings.
    """
    template = _TEMPLATES.get(comm_type, _TEMPLATES[CommunicationType.STATUS_UPDATE])
    return {
        "subject": template["subject"].format_map({**{"number": "", "priority": "", "state": "", "description": "", "business_impact": ""}, **incident_context}),
        "body": template["body"].format_map({**{"number": "", "priority": "", "state": "", "description": "", "business_impact": ""}, **incident_context}),
    }


def get_communications(incident_number: str) -> list[Communication]:
    """Return all communications for an incident, newest first."""
    comms = _comm_store.get(incident_number, [])
    return sorted(comms, key=lambda c: c.sent_at, reverse=True)


def add_communication(
    incident_number: str,
    payload: CommunicationCreate,
    sent_by: str = "System",
) -> Communication:
    """Record a new outbound communication."""
    comm = Communication(
        id=str(uuid.uuid4()),
        incident_number=incident_number,
        comm_type=payload.comm_type,
        subject=payload.subject,
        body=payload.body,
        recipients=payload.recipients,
        sent_at=datetime.utcnow(),
        sent_by=sent_by,
    )
    _comm_store.setdefault(incident_number, []).append(comm)
    logger.info(
        "Communication sent: %s [%s] for %s",
        comm.comm_type.value,
        comm.subject,
        incident_number,
    )
    return comm
