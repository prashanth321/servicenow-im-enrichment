"""
Enrichment tracker — idempotency guard, audit trail, and processing lock.

Prevents the same incident from being enriched multiple times (idempotency),
records what was enriched, when, and which steps succeeded (audit trail),
and ensures webhook + polling cannot process the same incident concurrently
(processing lock).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel

from utils import persistence
from utils.logger import get_logger

logger = get_logger(__name__)

_STORE_NAME = "enrichment_audit"


class EnrichmentStep(str, Enum):
    CI_LOOKUP = "ci_lookup"
    ONCALL_LOOKUP = "oncall_lookup"
    APP_LOOKUP = "app_lookup"
    IMPACT_DERIVATION = "impact_derivation"
    SN_UPDATE = "sn_update"


class StepResult(BaseModel):
    step: EnrichmentStep
    status: str  # "success", "skipped", "failed"
    detail: str = ""
    timestamp: str


class EnrichmentRecord(BaseModel):
    incident_number: str
    sys_id: str
    started_at: str
    completed_at: Optional[str] = None
    overall_status: str  # "complete", "partial", "failed"
    steps: list[StepResult] = []
    triggered_by: str = "poll"  # "poll" or "webhook"


def _load_store() -> dict[str, list[dict]]:
    return persistence.load(_STORE_NAME)


def _save_store() -> None:
    # Keep only last 5 enrichment records per incident
    trimmed = {}
    for k, v in _audit_store.items():
        trimmed[k] = v[-5:]
    persistence.save(_STORE_NAME, trimmed)


_audit_store: dict[str, list[dict]] = _load_store()

# In-flight processing lock: incident_number -> asyncio.Lock
_processing_locks: dict[str, asyncio.Lock] = {}

# Set of incident numbers currently being processed (for fast check)
_in_progress: set[str] = set()


def _get_lock(incident_number: str) -> asyncio.Lock:
    """Get or create an asyncio lock for an incident."""
    if incident_number not in _processing_locks:
        _processing_locks[incident_number] = asyncio.Lock()
    return _processing_locks[incident_number]


def is_recently_enriched(incident_number: str, window_seconds: int = 300) -> bool:
    """Check if the incident was successfully enriched within the given window.

    Returns True if there is a 'complete' or 'partial' enrichment record
    within the last `window_seconds`. This prevents re-processing incidents
    that got a None business_impact (partial enrichment) on every poll cycle.
    """
    records = _audit_store.get(incident_number, [])
    if not records:
        return False

    latest = records[-1]
    completed_at = latest.get("completed_at")
    if not completed_at:
        return False

    try:
        completed_dt = datetime.fromisoformat(completed_at)
        now = datetime.now(timezone.utc)
        elapsed = (now - completed_dt).total_seconds()
        return elapsed < window_seconds
    except (ValueError, TypeError):
        return False


def is_in_progress(incident_number: str) -> bool:
    """Check if the incident is currently being processed."""
    return incident_number in _in_progress


async def acquire_processing(incident_number: str) -> bool:
    """Try to acquire the processing lock for an incident.

    Returns True if acquired (caller should proceed with enrichment).
    Returns False if already in progress (caller should skip).
    """
    lock = _get_lock(incident_number)
    acquired = lock.locked()
    if acquired:
        return False
    await lock.acquire()
    _in_progress.add(incident_number)
    return True


def release_processing(incident_number: str) -> None:
    """Release the processing lock after enrichment completes."""
    _in_progress.discard(incident_number)
    lock = _processing_locks.get(incident_number)
    if lock and lock.locked():
        lock.release()


def start_enrichment(incident_number: str, sys_id: str, triggered_by: str) -> EnrichmentRecord:
    """Begin tracking an enrichment run."""
    record = EnrichmentRecord(
        incident_number=incident_number,
        sys_id=sys_id,
        started_at=datetime.now(timezone.utc).isoformat(),
        overall_status="in_progress",
        triggered_by=triggered_by,
    )
    return record


def record_step(record: EnrichmentRecord, step: EnrichmentStep, status: str, detail: str = "") -> None:
    """Record the result of an enrichment step."""
    record.steps.append(StepResult(
        step=step,
        status=status,
        detail=detail,
        timestamp=datetime.now(timezone.utc).isoformat(),
    ))


def complete_enrichment(record: EnrichmentRecord, overall_status: str) -> None:
    """Finalize the enrichment record and persist it."""
    record.completed_at = datetime.now(timezone.utc).isoformat()
    record.overall_status = overall_status

    _audit_store.setdefault(record.incident_number, []).append(record.model_dump())
    _save_store()

    logger.info(
        "Enrichment audit: %s status=%s triggered_by=%s steps=%d",
        record.incident_number,
        overall_status,
        record.triggered_by,
        len(record.steps),
    )


def get_audit_trail(incident_number: str) -> list[dict]:
    """Return the enrichment audit trail for an incident."""
    return _audit_store.get(incident_number, [])
