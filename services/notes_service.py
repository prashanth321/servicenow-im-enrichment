"""
Notes, Action Items, and Infrastructure Changes service.

Provides CRUD operations for the three tab-based data types in the
incident workspace panel.

Converted from NotesPanel.tsx / ActionItemsPanel.tsx / ChangesPanel.tsx.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from models.dashboard_schemas import (
    ActionItem,
    ActionItemCreate,
    ActionItemStatus,
    ActionItemUpdate,
    InfraChange,
    InfraChangeCreate,
    Note,
    NoteCreate,
)
from utils.logger import get_logger

# In-memory stores keyed by incident_number
_notes_store: dict[str, list[Note]] = {}
_actions_store: dict[str, list[ActionItem]] = {}
_changes_store: dict[str, list[InfraChange]] = {}

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def get_notes(incident_number: str) -> list[Note]:
    """Return all notes for an incident, newest first."""
    notes = _notes_store.get(incident_number, [])
    return sorted(notes, key=lambda n: n.created_at, reverse=True)


def add_note(incident_number: str, payload: NoteCreate) -> Note:
    """Add a timestamped note to an incident."""
    note = Note(
        id=str(uuid.uuid4()),
        incident_number=incident_number,
        content=payload.content,
        author=payload.author,
        created_at=datetime.utcnow(),
    )
    _notes_store.setdefault(incident_number, []).append(note)
    logger.info("Note added to %s by %s", incident_number, note.author)
    return note


def delete_note(incident_number: str, note_id: str) -> bool:
    """Delete a note by ID."""
    notes = _notes_store.get(incident_number, [])
    for i, n in enumerate(notes):
        if n.id == note_id:
            notes.pop(i)
            return True
    return False


# ---------------------------------------------------------------------------
# Action Items
# ---------------------------------------------------------------------------

def get_action_items(incident_number: str) -> list[ActionItem]:
    """Return all action items for an incident."""
    return _actions_store.get(incident_number, [])


def add_action_item(incident_number: str, payload: ActionItemCreate) -> ActionItem:
    """Create a new action item assigned during the incident."""
    item = ActionItem(
        id=str(uuid.uuid4()),
        incident_number=incident_number,
        description=payload.description,
        team=payload.team,
        assignee=payload.assignee,
        due_date=payload.due_date,
        status=ActionItemStatus.OPEN,
        created_at=datetime.utcnow(),
    )
    _actions_store.setdefault(incident_number, []).append(item)
    logger.info("Action item added to %s: %s", incident_number, item.description[:50])
    return item


def update_action_item(
    incident_number: str,
    item_id: str,
    payload: ActionItemUpdate,
) -> ActionItem | None:
    """Update an action item's status, assignee, or due date."""
    for item in get_action_items(incident_number):
        if item.id == item_id:
            if payload.status is not None:
                item.status = payload.status
            if payload.assignee is not None:
                item.assignee = payload.assignee
            if payload.due_date is not None:
                item.due_date = payload.due_date
            logger.info("Action item %s updated on %s", item_id, incident_number)
            return item
    return None


def delete_action_item(incident_number: str, item_id: str) -> bool:
    """Delete an action item by ID."""
    items = _actions_store.get(incident_number, [])
    for i, item in enumerate(items):
        if item.id == item_id:
            items.pop(i)
            return True
    return False


# ---------------------------------------------------------------------------
# Infrastructure Changes
# ---------------------------------------------------------------------------

def get_changes(incident_number: str) -> list[InfraChange]:
    """Return all infrastructure changes for an incident."""
    return _changes_store.get(incident_number, [])


def add_change(incident_number: str, payload: InfraChangeCreate) -> InfraChange:
    """Record an infrastructure change made during the incident."""
    change = InfraChange(
        id=str(uuid.uuid4()),
        incident_number=incident_number,
        description=payload.description,
        owner_team=payload.owner_team,
        assignee=payload.assignee,
        timestamp=datetime.utcnow(),
    )
    _changes_store.setdefault(incident_number, []).append(change)
    logger.info("Infra change recorded on %s: %s", incident_number, change.description[:50])
    return change


def delete_change(incident_number: str, change_id: str) -> bool:
    """Delete an infrastructure change record."""
    changes = _changes_store.get(incident_number, [])
    for i, c in enumerate(changes):
        if c.id == change_id:
            changes.pop(i)
            return True
    return False
