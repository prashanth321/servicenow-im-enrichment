"""
Communication tracking service.

Records outbound communications (status updates, customer impact notices,
escalations, resolution notices) sent during an incident. Also provides
email template rendering.

Converted from CommunicationPanel.tsx / CommunicationModal.
"""

from __future__ import annotations

import asyncio
import smtplib
import uuid
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import partial

from config.settings import settings
from models.dashboard_schemas import Communication, CommunicationCreate, CommunicationType
from utils.logger import get_logger
from utils import persistence
from utils.persistence import evict_oldest

_STORE_NAME = "communications"

def _load_store() -> dict[str, list[Communication]]:
    raw = persistence.load(_STORE_NAME)
    return {k: [Communication(**c) for c in v] for k, v in raw.items()}

def _save_store() -> None:
    evict_oldest(_comm_store)
    persistence.save(_STORE_NAME, {k: [c.model_dump() for c in v] for k, v in _comm_store.items()})

# Persistent store: incident_number -> list[Communication]
_comm_store: dict[str, list[Communication]] = _load_store()

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


async def add_communication(
    incident_number: str,
    payload: CommunicationCreate,
    sent_by: str = "System",
) -> Communication:
    """Record a new outbound communication and send email if SMTP is configured."""
    comm = Communication(
        id=str(uuid.uuid4()),
        incident_number=incident_number,
        comm_type=payload.comm_type,
        subject=payload.subject,
        body=payload.body,
        recipients=payload.recipients,
        sent_at=datetime.now(timezone.utc),
        sent_by=sent_by,
    )
    _comm_store.setdefault(incident_number, []).append(comm)
    _save_store()

    # Send actual email in a thread pool to avoid blocking the async loop
    if settings.smtp_host and payload.recipients:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, partial(_send_email, payload.subject, payload.body, payload.recipients)
            )
            logger.info(
                "Email sent: %s [%s] to %s for %s",
                comm.comm_type.value,
                comm.subject,
                ", ".join(payload.recipients),
                incident_number,
            )
        except Exception as exc:
            logger.error(
                "Failed to send email for %s: %s",
                incident_number,
                exc,
            )
    else:
        logger.info(
            "Communication recorded (no SMTP configured): %s [%s] for %s",
            comm.comm_type.value,
            comm.subject,
            incident_number,
        )

    return comm


def _send_email(subject: str, body: str, recipients: list[str]) -> None:
    """Send an email via SMTP."""
    msg = MIMEMultipart()
    msg["From"] = settings.smtp_from_email or settings.smtp_username
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.sendmail(msg["From"], recipients, msg.as_string())
