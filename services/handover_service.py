"""
Shift handover service.

Manages the ownership transfer workflow between incident managers,
including the mandatory 5-item safety checklist.

Converted from HandoverPanel.tsx / HandoverChecklistModal.tsx.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from models.dashboard_schemas import HandoverChecklist, HandoverRecord, HandoverRequest
from utils.logger import get_logger

# In-memory store: incident_number -> list[HandoverRecord]
_handover_store: dict[str, list[HandoverRecord]] = {}

# Current owner per incident
_owner_store: dict[str, str] = {}

logger = get_logger(__name__)


def get_current_owner(incident_number: str) -> str:
    """Return the current incident manager for an incident."""
    return _owner_store.get(incident_number, "Unassigned")


def set_initial_owner(incident_number: str, owner: str) -> None:
    """Set the initial owner when an incident is first loaded."""
    if incident_number not in _owner_store:
        _owner_store[incident_number] = owner


def get_handover_history(incident_number: str) -> list[HandoverRecord]:
    """Return all handover records for an incident."""
    return _handover_store.get(incident_number, [])


def validate_checklist(checklist: HandoverChecklist) -> list[str]:
    """Validate that all checklist items are completed.

    Returns a list of incomplete item names (empty list = all good).
    """
    incomplete: list[str] = []
    if not checklist.status_reviewed:
        incomplete.append("Status reviewed")
    if not checklist.actions_transferred:
        incomplete.append("Actions transferred")
    if not checklist.stakeholder_comms_shared:
        incomplete.append("Stakeholder communications shared")
    if not checklist.vendor_status_confirmed:
        incomplete.append("Vendor status confirmed")
    if not checklist.escalation_points_identified:
        incomplete.append("Escalation points identified")
    return incomplete


def transfer_ownership(
    incident_number: str,
    request: HandoverRequest,
    current_manager: str = "",
) -> HandoverRecord | None:
    """Execute a shift handover after validating the checklist.

    Args:
        incident_number: The incident to transfer.
        request: Contains the target manager and completed checklist.
        current_manager: The manager handing off (auto-detected if empty).

    Returns:
        The HandoverRecord on success, or None if checklist is incomplete.
    """
    # Validate all checklist items are checked
    incomplete = validate_checklist(request.checklist)
    if incomplete:
        logger.warning(
            "Handover blocked for %s — incomplete items: %s",
            incident_number,
            ", ".join(incomplete),
        )
        return None

    from_manager = current_manager or get_current_owner(incident_number)

    record = HandoverRecord(
        id=str(uuid.uuid4()),
        incident_number=incident_number,
        from_manager=from_manager,
        to_manager=request.target_manager,
        checklist=request.checklist,
        transferred_at=datetime.utcnow(),
    )

    _handover_store.setdefault(incident_number, []).append(record)
    _owner_store[incident_number] = request.target_manager

    logger.info(
        "Ownership transferred on %s: %s -> %s",
        incident_number,
        from_manager,
        request.target_manager,
    )
    return record
