"""
Priority escalation tracking service.

Records priority changes over the life of an incident, providing an
audit trail of when and why the priority was escalated or de-escalated.
Fetches historical data from ServiceNow's sys_audit table when available.

Converted from PriorityTracker.tsx.
"""

from __future__ import annotations

from datetime import datetime

from models.dashboard_schemas import PriorityChange
from utils.api_client import ServiceNowClient
from utils.exceptions import ServiceNowAPIError
from utils.logger import get_logger
from utils import persistence

_STORE_NAME = "priority"

def _load_store() -> dict[str, list[PriorityChange]]:
    raw = persistence.load(_STORE_NAME)
    return {k: [PriorityChange(**p) for p in v] for k, v in raw.items()}

def _save_store() -> None:
    persistence.save(_STORE_NAME, {k: [p.model_dump() for p in v] for k, v in _priority_store.items()})

# Persistent store: incident_number -> list[PriorityChange]
_priority_store: dict[str, list[PriorityChange]] = _load_store()

logger = get_logger(__name__)


def get_priority_history(incident_number: str) -> list[PriorityChange]:
    """Return the priority change history for an incident, oldest first."""
    changes = _priority_store.get(incident_number, [])
    return sorted(changes, key=lambda c: c.changed_at)


def add_priority_change(
    incident_number: str,
    from_priority: str,
    to_priority: str,
    changed_by: str = "",
    reason: str = "",
) -> PriorityChange:
    """Record a priority change event."""
    change = PriorityChange(
        from_priority=from_priority,
        to_priority=to_priority,
        changed_at=datetime.utcnow(),
        changed_by=changed_by,
        reason=reason,
    )
    _priority_store.setdefault(incident_number, []).append(change)
    _save_store()
    logger.info(
        "Priority change on %s: P%s -> P%s by %s",
        incident_number,
        from_priority,
        to_priority,
        changed_by or "system",
    )
    return change


async def fetch_priority_history_from_sn(
    client: ServiceNowClient,
    incident_sys_id: str,
    incident_number: str = "N/A",
) -> list[PriorityChange]:
    """Fetch priority change history from ServiceNow's audit table.

    Queries ``sys_audit`` for changes to the ``priority`` field on the
    specified incident record.
    """
    log = get_logger(__name__, incident_number)

    try:
        response = await client.get(
            "/api/now/table/sys_audit",
            params={
                "sysparm_query": (
                    f"documentkey={incident_sys_id}"
                    "^fieldname=priority"
                    "^ORDERBYsys_created_on"
                ),
                "sysparm_fields": "oldvalue,newvalue,sys_created_on,user",
                "sysparm_display_value": "true",
            },
        )

        if response.status_code >= 400:
            log.warning("Audit query failed — HTTP %s", response.status_code)
            return []

        results: list[dict] = response.json().get("result", [])
        changes: list[PriorityChange] = []

        for record in results:
            try:
                changes.append(PriorityChange(
                    from_priority=record.get("oldvalue", ""),
                    to_priority=record.get("newvalue", ""),
                    changed_at=datetime.fromisoformat(
                        record.get("sys_created_on", "").replace(" ", "T")
                    ),
                    changed_by=record.get("user", ""),
                ))
            except (ValueError, TypeError):
                continue

        # Cache the results
        _priority_store[incident_number] = changes
        _save_store()
        log.info("Fetched %d priority changes from SN audit", len(changes))
        return changes

    except ServiceNowAPIError:
        raise
    except Exception as exc:
        log.error("Error fetching priority history: %s", exc)
        return []
