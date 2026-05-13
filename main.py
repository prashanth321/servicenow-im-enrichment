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
import hmac
from contextlib import asynccontextmanager

from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

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
from utils.correlation import CorrelationIDMiddleware
from utils.api_client import ServiceNowClient, sanitize_sysparm
from utils.enrichment_tracker import (
    EnrichmentStep,
    acquire_processing,
    complete_enrichment,
    is_in_progress,
    is_recently_enriched,
    record_step,
    release_processing,
    start_enrichment,
)
from utils.exceptions import CINotFoundError, OnCallFetchError, ServiceNowAPIError
from utils.logger import get_logger
from utils.sn_fields import extract_value

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Core enrichment orchestration
# ---------------------------------------------------------------------------

async def enrich_incident(payload: WebhookPayload, triggered_by: str = "poll") -> EnrichedIncident:
    """Run the full enrichment pipeline for a single incident.

    Includes idempotency guard (skips if recently enriched), processing lock
    (prevents concurrent processing), parallel independent lookups, and
    a full audit trail of every step.

    Args:
        payload: The inbound incident data (from webhook or polling).
        triggered_by: Source that triggered enrichment ("poll" or "webhook").

    Returns:
        The ``EnrichedIncident`` with all available enrichment applied.

    Raises:
        RuntimeError: If enrichment is skipped due to idempotency or lock.
    """
    inc_logger = get_logger(__name__, payload.number)

    # --- Idempotency guard ---
    if is_recently_enriched(payload.number, window_seconds=settings.polling_interval_seconds):
        inc_logger.info("Skipping %s — already enriched within the polling window", payload.number)
        raise RuntimeError(f"Incident {payload.number} already enriched recently")

    # --- Processing lock (prevents webhook + poll race condition) ---
    acquired = await acquire_processing(payload.number)
    if not acquired:
        inc_logger.info("Skipping %s — already being processed", payload.number)
        raise RuntimeError(f"Incident {payload.number} is already being processed")

    # Start audit record
    audit = start_enrichment(payload.number, payload.sys_id, triggered_by)
    enrichment_status = "complete"

    ci_details: CIDetails | None = None
    oncall_details = None
    app_details = None

    try:
        async with ServiceNowClient() as client:

            # --- Step 1: CMDB / CI lookup ---
            if payload.cmdb_ci:
                try:
                    ci_details = await fetch_ci_details(client, payload.cmdb_ci, payload.number)
                    inc_logger.info("CI details fetched successfully")
                    record_step(audit, EnrichmentStep.CI_LOOKUP, "success")
                except CINotFoundError:
                    inc_logger.warning("CI %s not found — continuing with partial enrichment", payload.cmdb_ci)
                    enrichment_status = "partial"
                    record_step(audit, EnrichmentStep.CI_LOOKUP, "failed", f"CI {payload.cmdb_ci} not found")
                except ServiceNowAPIError as exc:
                    inc_logger.error("CMDB fetch failed: %s", exc)
                    enrichment_status = "partial"
                    record_step(audit, EnrichmentStep.CI_LOOKUP, "failed", str(exc))
            else:
                inc_logger.warning("No CMDB CI linked to incident — skipping CI enrichment")
                enrichment_status = "partial"
                record_step(audit, EnrichmentStep.CI_LOOKUP, "skipped", "No CMDB CI linked")

            # --- Steps 2 & 3 in parallel: On-call + App lookup ---
            support_group = (
                (ci_details.support_group if ci_details else None)
                or payload.assignment_group
            )
            app_sys_id = ci_details.business_application if ci_details else None

            async def _fetch_oncall():
                nonlocal oncall_details, enrichment_status
                if support_group:
                    try:
                        oncall_details = await fetch_oncall_details(client, support_group, payload.number)
                        inc_logger.info("On-call details fetched successfully")
                        record_step(audit, EnrichmentStep.ONCALL_LOOKUP, "success")
                    except (OnCallFetchError, ServiceNowAPIError) as exc:
                        inc_logger.error("On-call fetch failed: %s", exc)
                        enrichment_status = "partial"
                        record_step(audit, EnrichmentStep.ONCALL_LOOKUP, "failed", str(exc))
                else:
                    inc_logger.warning("No support group available — skipping on-call lookup")
                    record_step(audit, EnrichmentStep.ONCALL_LOOKUP, "skipped", "No support group")

            async def _fetch_app():
                nonlocal app_details, enrichment_status
                if app_sys_id:
                    try:
                        app_details = await fetch_app_details(client, app_sys_id, payload.number)
                        inc_logger.info("Business app details fetched successfully")
                        record_step(audit, EnrichmentStep.APP_LOOKUP, "success")
                    except ServiceNowAPIError as exc:
                        inc_logger.error("App details fetch failed: %s", exc)
                        enrichment_status = "partial"
                        record_step(audit, EnrichmentStep.APP_LOOKUP, "failed", str(exc))
                else:
                    inc_logger.warning("No business application linked — skipping app lookup")
                    record_step(audit, EnrichmentStep.APP_LOOKUP, "skipped", "No business app linked")

            # Run on-call and app lookups concurrently
            await asyncio.gather(_fetch_oncall(), _fetch_app())

            # --- Step 4: Derive business impact ---
            service_tier = ci_details.service_mapping if ci_details else None
            criticality = None
            business_impact = derive_business_impact(service_tier, criticality)
            inc_logger.info("Business impact derived: %s", business_impact)
            record_step(audit, EnrichmentStep.IMPACT_DERIVATION, "success", f"impact={business_impact}")

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
                record_step(audit, EnrichmentStep.SN_UPDATE, "failed", "update_incident returned False")
                enrichment_status = "partial"
            else:
                inc_logger.info("Incident %s enrichment complete (status=%s)", payload.number, enrichment_status)
                record_step(audit, EnrichmentStep.SN_UPDATE, "success")

        # Finalize audit
        complete_enrichment(audit, enrichment_status)
        return enriched

    finally:
        release_processing(payload.number)


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
                    try:
                        results: list[dict] = response.json().get("result", [])
                    except Exception:
                        poll_logger.error(
                            "Polling response is not valid JSON (status %s) — "
                            "ServiceNow instance may be hibernated or unreachable",
                            response.status_code,
                        )
                        await asyncio.sleep(settings.polling_interval_seconds)
                        continue
                    poll_logger.info("Polling found %d candidate incident(s)", len(results))

                    # Bounded concurrency: process up to 5 incidents at once
                    _sem = asyncio.Semaphore(5)

                    async def _enrich_one(record: dict) -> None:
                        inc_number = record.get("number", "UNKNOWN")
                        try:
                            # Skip if recently enriched (idempotency guard)
                            if is_recently_enriched(inc_number, settings.polling_interval_seconds):
                                poll_logger.debug("Skipping %s — recently enriched", inc_number)
                                return
                            # Skip if already in progress (race guard)
                            if is_in_progress(inc_number):
                                poll_logger.debug("Skipping %s — already in progress", inc_number)
                                return

                            payload = WebhookPayload(
                                sys_id=record.get("sys_id", ""),
                                number=inc_number,
                                priority=str(record.get("priority", "")),
                                cmdb_ci=extract_value(record.get("cmdb_ci")),
                                short_description=record.get("short_description", ""),
                                assignment_group=extract_value(record.get("assignment_group")),
                            )
                            async with _sem:
                                await enrich_incident(payload, triggered_by="poll")
                        except RuntimeError:
                            # Idempotency/lock skip — already logged inside enrich_incident
                            pass
                        except Exception:
                            poll_logger.exception(
                                "Unhandled error enriching incident %s", inc_number,
                            )

                    await asyncio.gather(*[_enrich_one(r) for r in results])

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
    description="Enriches P2 incidents with CMDB, on-call, app, impact data, and full IM dashboard APIs.",
    version="2.0.0",
    lifespan=lifespan,
)

# Rate limiter — 60 requests/minute per IP for all endpoints
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — allow the dashboard frontend to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Content Security Policy middleware
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402


class CSPMiddleware(BaseHTTPMiddleware):
    """Inject Content-Security-Policy headers on every response."""

    _CSP = "; ".join([
        "default-src 'self'",
        "script-src 'self' https://cdn.tailwindcss.com https://unpkg.com 'unsafe-inline'",
        "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data:",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ])

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = self._CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response


app.add_middleware(CSPMiddleware)

# Per-request correlation ID
app.add_middleware(CorrelationIDMiddleware)

# Register auth routes
from routes.auth_routes import router as auth_router  # noqa: E402
app.include_router(auth_router)

# Register the major incidents routes (BEFORE dashboard to avoid path conflicts)
from routes.incidents_routes import router as incidents_router  # noqa: E402
app.include_router(incidents_router)

# Register the dashboard routes (converted from React IM Dashboard)
from routes.dashboard_routes import router as dashboard_router  # noqa: E402
from routes.dashboard_routes import _load_contacts  # noqa: E402
app.include_router(dashboard_router)

from services.auth_service import get_current_user  # noqa: E402


@app.get("/contacts")
def get_contacts(_user: dict = Depends(get_current_user)):
    """Return the email contacts configuration."""
    return _load_contacts()


@app.get("/users/search")
async def search_servicenow_users(q: str = "", _user: dict = Depends(get_current_user)):
    """Search ServiceNow sys_user table by name (for handover autocomplete)."""
    if not q or len(q) < 2:
        return []
    safe_q = sanitize_sysparm(q)
    async with ServiceNowClient() as client:
        resp = await client.get(
            "/api/now/table/sys_user",
            params={
                "sysparm_query": f"nameLIKE{safe_q}^active=true",
                "sysparm_fields": "sys_id,name,email,title",
                "sysparm_limit": "10",
            },
        )
        results = resp.json().get("result", [])
        return [
            {"sys_id": u.get("sys_id", ""), "name": u.get("name", ""), "email": u.get("email", ""), "title": u.get("title", "")}
            for u in results
        ]


# Serve the static dashboard UI
_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Dashboard UI & P2 incident list
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def serve_login():
    """Serve the Login page at the root URL."""
    return FileResponse(str(_STATIC_DIR / "login.html"))


@app.get("/login", include_in_schema=False)
async def serve_login_page():
    """Serve the Login page."""
    return FileResponse(str(_STATIC_DIR / "login.html"))


@app.get("/dashboard", include_in_schema=False)
async def serve_im_dashboard():
    """Serve the IM Dashboard HTML page."""
    return FileResponse(str(_STATIC_DIR / "dashboard.html"))


@app.get("/incidents-view", include_in_schema=False)
async def serve_major_incidents():
    """Serve the Major Incidents page."""
    return FileResponse(str(_STATIC_DIR / "major_incidents.html"))


@app.get("/incidents/list/active-p2")
async def list_active_p2(_user: dict = Depends(get_current_user)):
    """Return active P2 incidents for the dashboard selector dropdown."""
    async with ServiceNowClient() as client:
        response = await client.get(
            "/api/now/table/incident",
            params={
                "sysparm_query": "priority=2^active=true^ORDERBYDESCopened_at",
                "sysparm_fields": "number,short_description,state,assigned_to",
                "sysparm_display_value": "true",
                "sysparm_limit": "25",
            },
        )
        return response.json().get("result", [])


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------

@app.post("/webhook", response_model=dict)
@limiter.limit("30/minute")
async def webhook_handler(request: Request) -> JSONResponse:
    """Receive a ServiceNow incident event and trigger enrichment.

    The endpoint accepts the JSON payload sent by a ServiceNow Business Rule
    or outbound REST Message.  Requires ``X-Webhook-Secret`` header matching
    the configured ``WEBHOOK_SECRET`` env var.  Only incidents with
    ``priority == "2"`` (P2) are processed; all others are acknowledged and
    skipped.
    """
    wh_logger = get_logger(__name__, "WEBHOOK")

    # Verify webhook shared secret — MANDATORY
    if not settings.webhook_secret:
        wh_logger.error("Webhook rejected — WEBHOOK_SECRET not configured on server")
        raise HTTPException(status_code=503, detail="Webhook authentication not configured")

    provided = request.headers.get("X-Webhook-Secret", "")
    if not hmac.compare_digest(provided, settings.webhook_secret):
        wh_logger.warning("Webhook rejected — invalid or missing X-Webhook-Secret")
        raise HTTPException(status_code=403, detail="Invalid webhook secret")


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
        enriched = await enrich_incident(payload, triggered_by="webhook")
        return JSONResponse(
            status_code=200,
            content={
                "status": "enriched",
                "incident": payload.number,
                "enrichment_status": enriched.enrichment_status,
                "business_impact": enriched.business_impact,
            },
        )
    except RuntimeError as exc:
        # Idempotency guard or processing lock prevented enrichment
        wh_logger.info("Enrichment skipped for %s: %s", payload.number, exc)
        return JSONResponse(
            status_code=200,
            content={"status": "skipped", "message": str(exc)},
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
    """Readiness probe — verifies ServiceNow connectivity."""
    try:
        async with ServiceNowClient() as client:
            resp = await client.get(
                "/api/now/table/incident",
                params={"sysparm_limit": "1", "sysparm_fields": "sys_id"},
            )
            if resp.status_code < 400:
                return {"status": "ok", "servicenow": "reachable"}
            return JSONResponse(
                status_code=503,
                content={"status": "degraded", "servicenow": f"HTTP {resp.status_code}"},
            )
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "servicenow": str(exc)},
        )


# ---------------------------------------------------------------------------
# Enrichment audit trail
# ---------------------------------------------------------------------------

from utils.enrichment_tracker import get_audit_trail  # noqa: E402


@app.get("/enrichment/audit/{incident_number}")
async def get_enrichment_audit(incident_number: str, _user: dict = Depends(get_current_user)):
    """Return the enrichment audit trail for an incident.

    Shows what was enriched, when, which steps succeeded/failed, and
    whether the trigger was a webhook or polling cycle.
    """
    return get_audit_trail(incident_number)


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
