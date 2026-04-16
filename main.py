"""
ServiceNow Incident Management Enrichment Service — entry point.

Runs a FastAPI application that:
1. Exposes ``POST /webhook`` for real-time incident events from ServiceNow
   Business Rules / REST Messages.
2. Starts a background **polling loop** (via ``asyncio``) that periodically
   queries ServiceNow for unprocessed P2 incidents as a fallback mechanism.

Both modes run concurrently using FastAPI lifespan events.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from config.settings import settings
from models.schemas import (
    CIDetails,
    EnrichedIncident,
    WebhookPayload,
)
from services.app_service import fetch_app_details
from services.cmdb_service import fetch_ci_details
from services.impact_service import derive_business_impact
from services.incident_service import fetch_incident, update_incident
from services.oncall_service import fetch_oncall_details
from utils.api_client import ServiceNowClient
from utils.exceptions import CINotFoundError, OnCallFetchError, ServiceNowAPIError
from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Core enrichment orchestration
# ---------------------------------------------------------------------------

async def enrich_incident(payload: WebhookPayload) -> EnrichedIncident:
    """Run the full enrichment pipeline for a single incident.

    Steps:
        1. Fetch CI/CMDB data (skip gracefully if CI missing).
        2. Fetch on-call details for the CI's support group.
        3. Fetch business application metadata.
        4. Derive business impact from tier + criticality.
        5. Write the enriched data back to the incident.

    Args:
        payload: The inbound incident data (from webhook or polling).

    Returns:
        The ``EnrichedIncident`` with all available enrichment applied.
    """
    inc_logger = get_logger(__name__, payload.number)
    enrichment_status = "complete"

    ci_details: CIDetails | None = None
    oncall_details = None
    app_details = None

    async with ServiceNowClient() as client:

        # --- Step 1: CMDB / CI lookup ---
        if payload.cmdb_ci:
            try:
                ci_details = await fetch_ci_details(client, payload.cmdb_ci, payload.number)
                inc_logger.info("CI details fetched successfully")
            except CINotFoundError:
                inc_logger.warning("CI %s not found — continuing with partial enrichment", payload.cmdb_ci)
                enrichment_status = "partial"
            except ServiceNowAPIError as exc:
                inc_logger.error("CMDB fetch failed: %s", exc)
                enrichment_status = "partial"
        else:
            inc_logger.warning("No CMDB CI linked to incident — skipping CI enrichment")
            enrichment_status = "partial"

        # --- Step 2: On-call lookup ---
        support_group = (
            (ci_details.support_group if ci_details else None)
            or payload.assignment_group
        )
        if support_group:
            try:
                oncall_details = await fetch_oncall_details(client, support_group, payload.number)
                inc_logger.info("On-call details fetched successfully")
            except (OnCallFetchError, ServiceNowAPIError) as exc:
                inc_logger.error("On-call fetch failed: %s", exc)
                enrichment_status = "partial"
        else:
            inc_logger.warning("No support group available — skipping on-call lookup")

        # --- Step 3: Business application lookup ---
        app_sys_id = ci_details.business_application if ci_details else None
        if app_sys_id:
            try:
                app_details = await fetch_app_details(client, app_sys_id, payload.number)
                inc_logger.info("Business app details fetched successfully")
            except ServiceNowAPIError as exc:
                inc_logger.error("App details fetch failed: %s", exc)
                enrichment_status = "partial"
        else:
            inc_logger.warning("No business application linked — skipping app lookup")

        # --- Step 4: Derive business impact ---
        # Use service_mapping as a proxy for tier; support_group criticality
        # would come from the CI record in a real deployment.
        service_tier = ci_details.service_mapping if ci_details else None
        criticality = None  # Could be enriched from additional CMDB fields
        business_impact = derive_business_impact(service_tier, criticality)
        inc_logger.info("Business impact derived: %s", business_impact)

        # --- Step 5: Assemble enriched incident ---
        enriched = EnrichedIncident(
            sys_id=payload.sys_id,
            number=payload.number,
            short_description=payload.short_description,
            ci_details=ci_details,
            oncall_details=oncall_details,
            app_details=app_details,
            business_impact=business_impact,
            enrichment_status=enrichment_status,
        )

        # --- Step 6: Write enriched data back to ServiceNow ---
        success = await update_incident(client, enriched)
        if not success:
            inc_logger.error("Failed to update incident %s with enrichment data", payload.number)
        else:
            inc_logger.info("Incident %s enrichment complete (status=%s)", payload.number, enrichment_status)

    return enriched


# ---------------------------------------------------------------------------
# Polling loop
# ---------------------------------------------------------------------------

async def _polling_loop() -> None:
    """Periodically query ServiceNow for new P2 incidents and enrich them.

    Runs indefinitely at the interval configured in ``settings.polling_interval_seconds``.
    Errors on individual incidents are logged but never crash the loop.
    """
    poll_logger = get_logger(__name__, "POLLER")
    poll_logger.info(
        "Polling loop started — interval=%ds",
        settings.polling_interval_seconds,
    )

    while True:
        try:
            async with ServiceNowClient() as client:
                # Query for open P2 incidents that haven't been enriched yet.
                # The sysparm_query filter looks for priority=2 and a missing
                # business_impact field (or a custom marker field).
                response = await client.get(
                    "/api/now/table/incident",
                    params={
                        "sysparm_query": "priority=2^business_impactISEMPTY^stateIN1,2",
                        "sysparm_fields": "sys_id,number,priority,cmdb_ci,short_description,assignment_group",
                        "sysparm_limit": "20",
                    },
                )

                if response.status_code >= 400:
                    poll_logger.error("Polling query failed — HTTP %s", response.status_code)
                else:
                    results: list[dict] = response.json().get("result", [])
                    poll_logger.info("Polling found %d candidate incident(s)", len(results))

                    for record in results:
                        try:
                            def _val(field: object) -> str | None:
                                if isinstance(field, dict):
                                    return field.get("value") or None
                                if isinstance(field, str) and field.strip():
                                    return field.strip()
                                return None

                            payload = WebhookPayload(
                                sys_id=record.get("sys_id", ""),
                                number=record.get("number", "UNKNOWN"),
                                priority=str(record.get("priority", "")),
                                cmdb_ci=_val(record.get("cmdb_ci")),
                                short_description=record.get("short_description", ""),
                                assignment_group=_val(record.get("assignment_group")),
                            )
                            await enrich_incident(payload)
                        except Exception:
                            poll_logger.exception(
                                "Unhandled error enriching incident %s",
                                record.get("number", "UNKNOWN"),
                            )

        except Exception:
            poll_logger.exception("Unhandled error in polling loop iteration")

        await asyncio.sleep(settings.polling_interval_seconds)


# ---------------------------------------------------------------------------
# FastAPI lifespan — starts the polling loop alongside the web server
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup/shutdown for the FastAPI application.

    On startup the background polling task is created; on shutdown it is
    cancelled cleanly.
    """
    poll_task = asyncio.create_task(_polling_loop())
    logger.info("FastAPI application started — webhook + polling active")
    yield
    poll_task.cancel()
    try:
        await poll_task
    except asyncio.CancelledError:
        logger.info("Polling loop cancelled during shutdown")


app = FastAPI(
    title="ServiceNow IM Enrichment Service",
    description="Enriches P2 incidents with CMDB, on-call, app, and impact data.",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------

@app.post("/webhook", response_model=dict)
async def webhook_handler(request: Request) -> JSONResponse:
    """Receive a ServiceNow incident event and trigger enrichment.

    The endpoint accepts the JSON payload sent by a ServiceNow Business Rule
    or outbound REST Message. Only incidents with ``priority == "2"`` (P2)
    are processed; all others are acknowledged and skipped.

    **Sample inbound payload:**

    .. code-block:: json

        {
            "sys_id": "a1b2c3d4e5f6...",
            "number": "INC0012345",
            "priority": "2",
            "cmdb_ci": "abc123def456...",
            "short_description": "Payment gateway timeout",
            "assignment_group": "xyz789..."
        }

    Returns:
        JSON with ``status`` and ``message`` fields.
    """
    wh_logger = get_logger(__name__, "WEBHOOK")

    try:
        body: dict = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    wh_logger.info("Webhook received: %s", body.get("number", "UNKNOWN"))

    # Validate payload against the schema
    try:
        payload = WebhookPayload(**body)
    except Exception as exc:
        wh_logger.error("Payload validation failed: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc))

    # Only enrich P2 incidents
    if payload.priority != "2":
        wh_logger.info(
            "Skipping incident %s — priority %s is not P2",
            payload.number,
            payload.priority,
        )
        return JSONResponse(
            status_code=200,
            content={"status": "skipped", "message": f"Priority {payload.priority} is not P2"},
        )

    # Run enrichment asynchronously (don't block the webhook response for too long)
    try:
        enriched = await enrich_incident(payload)
        return JSONResponse(
            status_code=200,
            content={
                "status": "enriched",
                "incident": payload.number,
                "enrichment_status": enriched.enrichment_status,
                "business_impact": enriched.business_impact,
            },
        )
    except Exception:
        wh_logger.exception("Enrichment failed for %s", payload.number)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Enrichment failed for {payload.number}"},
        )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check() -> dict:
    """Simple liveness probe."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Run with uvicorn when executed directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
