"""
Pydantic models for request/response payloads used throughout the enrichment pipeline.

These schemas validate data flowing between the webhook/polling trigger, the
various ServiceNow API calls, and the final incident update.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Inbound webhook payload
# ---------------------------------------------------------------------------

class WebhookPayload(BaseModel):
    """Represents the incoming ServiceNow Business Rule / REST Message payload.

    Fields mirror the key columns on the incident table that the enrichment
    pipeline needs to start processing.
    """

    sys_id: str = Field(..., description="Unique sys_id of the incident record")
    number: str = Field(..., description="Human-readable incident number (e.g. INC0012345)")
    priority: str = Field(..., description="Priority value — only '2' (P2) will be processed")
    cmdb_ci: str | None = Field(None, description="sys_id of the linked Configuration Item")
    short_description: str = Field("", description="Short description / title of the incident")
    assignment_group: str | None = Field(None, description="sys_id of the assignment group")


# ---------------------------------------------------------------------------
# Enrichment detail models
# ---------------------------------------------------------------------------

class CIDetails(BaseModel):
    """Configuration Item details fetched from the CMDB."""

    ci_name: str | None = None
    business_application: str | None = None
    service_mapping: str | None = None
    support_group: str | None = None


class EscalationContact(BaseModel):
    """A single escalation contact returned from the on-call rota."""

    name: str
    email: str | None = None
    phone: str | None = None


class OnCallDetails(BaseModel):
    """Primary on-call person and their escalation chain."""

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    escalation_contacts: list[EscalationContact] = Field(default_factory=list)


class AppDetails(BaseModel):
    """Business application metadata from cmdb_ci_business_app."""

    application_owner: str | None = None
    technical_owner: str | None = None
    contact_email: str | None = None


# ---------------------------------------------------------------------------
# Combined / outbound models
# ---------------------------------------------------------------------------

class EnrichedIncident(BaseModel):
    """Full enrichment result combining all upstream data.

    This is the internal representation used before writing back to ServiceNow.
    """

    sys_id: str
    number: str
    short_description: str = ""
    ci_details: CIDetails | None = None
    oncall_details: OnCallDetails | None = None
    app_details: AppDetails | None = None
    business_impact: str = "Medium"
    enrichment_status: str = "complete"  # "complete" | "partial"


class UpdatePayload(BaseModel):
    """Fields PATCHed back to the ServiceNow incident record.

    Maps to actual incident table column names (including custom u_ prefixed fields).
    """

    business_impact: str | None = None
    application_owner: str | None = None
    u_technical_owner: str | None = None
    support_group: str | None = None
    work_notes: str | None = None
