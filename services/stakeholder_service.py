"""
Stakeholder management service.

Tracks stakeholders involved in an incident — people who need visibility
or are actively participating in resolution.

Converted from StakeholdersPanel.tsx.
"""

from __future__ import annotations

import uuid

from models.dashboard_schemas import Stakeholder, StakeholderCreate
from utils.logger import get_logger
from utils import persistence

_STORE_NAME = "stakeholders"

def _load_store() -> dict[str, list[Stakeholder]]:
    raw = persistence.load(_STORE_NAME)
    return {k: [Stakeholder(**s) for s in v] for k, v in raw.items()}

def _save_store() -> None:
    persistence.save(_STORE_NAME, {k: [s.model_dump() for s in v] for k, v in _stakeholder_store.items()})

# Persistent store: incident_number -> list[Stakeholder]
_stakeholder_store: dict[str, list[Stakeholder]] = _load_store()

logger = get_logger(__name__)


def get_stakeholders(incident_number: str) -> list[Stakeholder]:
    """Return all stakeholders for an incident."""
    return _stakeholder_store.get(incident_number, [])


def add_stakeholder(incident_number: str, payload: StakeholderCreate) -> Stakeholder:
    """Add a stakeholder to an incident."""
    stakeholder = Stakeholder(
        id=str(uuid.uuid4()),
        name=payload.name,
        role=payload.role,
        team=payload.team,
        email=payload.email,
        phone=payload.phone,
    )
    _stakeholder_store.setdefault(incident_number, []).append(stakeholder)
    _save_store()
    logger.info("Stakeholder added: %s (%s) to %s", stakeholder.name, stakeholder.role, incident_number)
    return stakeholder


def remove_stakeholder(incident_number: str, stakeholder_id: str) -> bool:
    """Remove a stakeholder from an incident."""
    stakeholders = _stakeholder_store.get(incident_number, [])
    for i, s in enumerate(stakeholders):
        if s.id == stakeholder_id:
            stakeholders.pop(i)
            _save_store()
            logger.info("Stakeholder removed: %s from %s", stakeholder_id, incident_number)
            return True
    return False
