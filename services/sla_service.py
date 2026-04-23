"""
SLA Clock management service.

Tracks SLA countdown timers per incident. Clocks tick in real-time and are
stored in memory (keyed by incident number). Supports create, pause, resume,
stop, and breach detection.

Converted from SLAClockPanel.tsx.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from models.dashboard_schemas import SLAClock, SLAClockCreate, SLAStatus
from utils.logger import get_logger

# In-memory store: incident_number -> list[SLAClock]
_sla_store: dict[str, list[SLAClock]] = {}

logger = get_logger(__name__)


def _default_clocks(incident_number: str) -> list[SLAClock]:
    """Create the two default SLA clocks for a new incident."""
    return [
        SLAClock(
            id=str(uuid.uuid4()),
            label="Customer Update SLA",
            target_minutes=30,
            remaining_seconds=30 * 60,
            status=SLAStatus.RUNNING,
        ),
        SLAClock(
            id=str(uuid.uuid4()),
            label="Resolution ETA",
            target_minutes=120,
            remaining_seconds=120 * 60,
            status=SLAStatus.RUNNING,
        ),
    ]


def get_clocks(incident_number: str) -> list[SLAClock]:
    """Return all SLA clocks for an incident, creating defaults if none exist."""
    if incident_number not in _sla_store:
        _sla_store[incident_number] = _default_clocks(incident_number)
    return _sla_store[incident_number]


def add_clock(incident_number: str, payload: SLAClockCreate) -> SLAClock:
    """Add a new SLA clock to an incident."""
    clock = SLAClock(
        id=str(uuid.uuid4()),
        label=payload.label,
        target_minutes=payload.target_minutes,
        remaining_seconds=payload.target_minutes * 60,
        status=SLAStatus.RUNNING,
    )
    clocks = get_clocks(incident_number)
    clocks.append(clock)
    logger.info("SLA clock added: %s for %s", clock.label, incident_number)
    return clock


def update_clock_status(
    incident_number: str,
    clock_id: str,
    new_status: SLAStatus,
) -> SLAClock | None:
    """Update the status of a specific SLA clock (pause/resume/stop)."""
    for clock in get_clocks(incident_number):
        if clock.id == clock_id:
            clock.status = new_status
            logger.info(
                "SLA clock %s (%s) -> %s",
                clock.label,
                incident_number,
                new_status.value,
            )
            return clock
    return None


def delete_clock(incident_number: str, clock_id: str) -> bool:
    """Remove an SLA clock."""
    clocks = get_clocks(incident_number)
    for i, clock in enumerate(clocks):
        if clock.id == clock_id:
            clocks.pop(i)
            logger.info("SLA clock deleted: %s from %s", clock_id, incident_number)
            return True
    return False


def tick_clocks(incident_number: str, elapsed_seconds: int = 1) -> list[SLAClock]:
    """Decrement running clocks and detect breaches.

    Called periodically (e.g. every second) by the front-end or a background task.
    """
    for clock in get_clocks(incident_number):
        if clock.status == SLAStatus.RUNNING:
            clock.remaining_seconds -= elapsed_seconds
            if clock.remaining_seconds <= 0:
                clock.status = SLAStatus.BREACHED
                logger.warning(
                    "SLA BREACHED: %s on %s",
                    clock.label,
                    incident_number,
                )
    return _sla_store[incident_number]
