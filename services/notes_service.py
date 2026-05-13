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
from utils import persistence

_NOTES_STORE = "notes"
_ACTIONS_STORE = "actions"
_CHANGES_STORE = "changes"

def _load_notes() -> dict[str, list[Note]]:
    raw = persistence.load(_NOTES_STORE)
    return {k: [Note(**n) for n in v] for k, v in raw.items()}

def _load_actions() -> dict[str, list[ActionItem]]:
    raw = persistence.load(_ACTIONS_STORE)
    return {k: [ActionItem(**a) for a in v] for k, v in raw.items()}

def _load_changes() -> dict[str, list[InfraChange]]:
    raw = persistence.load(_CHANGES_STORE)
    return {k: [InfraChange(**c) for c in v] for k, v in raw.items()}

def _save_notes():
    persistence.save(_NOTES_STORE, {k: [n.model_dump() for n in v] for k, v in _notes_store.items()})

def _save_actions():
    persistence.save(_ACTIONS_STORE, {k: [a.model_dump() for a in v] for k, v in _actions_store.items()})

def _save_changes():
    persistence.save(_CHANGES_STORE, {k: [c.model_dump() for c in v] for k, v in _changes_store.items()})

# Persistent stores keyed by incident_number
_notes_store: dict[str, list[Note]] = _load_notes()
_actions_store: dict[str, list[ActionItem]] = _load_actions()
_changes_store: dict[str, list[InfraChange]] = _load_changes()

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
    _save_notes()
    logger.info("Note added to %s by %s", incident_number, note.author)
    return note


def delete_note(incident_number: str, note_id: str) -> bool:
    """Delete a note by ID."""
    notes = _notes_store.get(incident_number, [])
    for i, n in enumerate(notes):
        if n.id == note_id:
            notes.pop(i)
            _save_notes()
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
    _save_actions()
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
            _save_actions()
            logger.info("Action item %s updated on %s", item_id, incident_number)
            return item
    return None


def delete_action_item(incident_number: str, item_id: str) -> bool:
    """Delete an action item by ID."""
    items = _actions_store.get(incident_number, [])
    for i, item in enumerate(items):
        if item.id == item_id:
            items.pop(i)
            _save_actions()
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
    _save_changes()
    logger.info("Infra change recorded on %s: %s", incident_number, change.description[:50])
    return change


def delete_change(incident_number: str, change_id: str) -> bool:
    """Delete an infrastructure change record."""
    changes = _changes_store.get(incident_number, [])
    for i, c in enumerate(changes):
        if c.id == change_id:
            changes.pop(i)
            _save_changes()
            return True
    return False
