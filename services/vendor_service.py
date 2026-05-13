"""
Vendor information service.

Manages vendor contact details, support hours, and SLA terms associated
with incidents. Fetches vendor data from ServiceNow's vendor table when
available, with a fallback to in-memory storage.

Converted from VendorPanel.tsx.
"""

from __future__ import annotations

from models.dashboard_schemas import VendorInfo
from utils.api_client import ServiceNowClient
from utils.exceptions import ServiceNowAPIError
from utils.logger import get_logger
from utils.sn_fields import extract_value
from utils import persistence
from utils.persistence import evict_oldest

_STORE_NAME = "vendors"

def _load_store() -> dict[str, VendorInfo]:
    raw = persistence.load(_STORE_NAME)
    return {k: VendorInfo(**v) for k, v in raw.items()}

def _save_store() -> None:
    evict_oldest(_vendor_store)
    persistence.save(_STORE_NAME, {k: v.model_dump() for k, v in _vendor_store.items()})

# Persistent store: incident_number -> VendorInfo
_vendor_store: dict[str, VendorInfo] = _load_store()

logger = get_logger(__name__)


def get_vendor_info(incident_number: str) -> VendorInfo | None:
    """Return vendor info for an incident, or None if not available."""
    return _vendor_store.get(incident_number)


def set_vendor_info(incident_number: str, vendor: VendorInfo) -> VendorInfo:
    """Set or update vendor info for an incident."""
    _vendor_store[incident_number] = vendor
    _save_store()
    logger.info("Vendor info updated for %s: %s", incident_number, vendor.vendor_name)
    return vendor


async def fetch_vendor_from_servicenow(
    client: ServiceNowClient,
    vendor_sys_id: str,
    incident_number: str = "N/A",
) -> VendorInfo:
    """Fetch vendor details from the ServiceNow vendor table.

    Calls ``GET /api/now/table/core_company/{vendor_sys_id}``.

    Args:
        client: An initialised ServiceNowClient.
        vendor_sys_id: The sys_id of the vendor company record.
        incident_number: For contextual logging.

    Returns:
        A VendorInfo populated from ServiceNow data.
    """
    log = get_logger(__name__, incident_number)

    try:
        response = await client.get(f"/api/now/table/core_company/{vendor_sys_id}")

        if response.status_code >= 400:
            raise ServiceNowAPIError(
                f"Vendor lookup failed for {vendor_sys_id}",
                status_code=response.status_code,
            )

        data: dict = response.json().get("result", {})

        vendor = VendorInfo(
            vendor_name=data.get("name", "Unknown Vendor"),
            account_manager=data.get("u_account_manager"),
            support_email=data.get("email"),
            support_phone=data.get("phone"),
        )

        log.info("Vendor fetched from SN: %s", vendor.vendor_name)
        return vendor

    except ServiceNowAPIError:
        raise
    except Exception as exc:
        log.error("Error fetching vendor %s: %s", vendor_sys_id, exc)
        raise ServiceNowAPIError(f"Error fetching vendor {vendor_sys_id}") from exc


async def lookup_vendor_for_incident(
    client: ServiceNowClient,
    incident_number: str,
    cmdb_ci: str | None,
    assignment_group: str | None,
) -> VendorInfo | None:
    """Resolve vendor info for an incident via CI or assignment group.

    Returns cached data if already fetched for this incident.
    Otherwise tries, in order:
    1. CI record's ``vendor`` / ``manufacturer`` reference.
    2. Assignment group's ``u_vendor`` / ``company`` reference.

    Returns ``None`` if neither lookup yields a vendor.
    """
    # Return cached vendor if available (avoids re-fetching on every load)
    cached = _vendor_store.get(incident_number)
    if cached is not None:
        return cached

    log = get_logger(__name__, incident_number)

    # -- 1. Try CI's vendor/manufacturer --
    if cmdb_ci:
        try:
            ci_resp = await client.get(
                f"/api/now/table/cmdb_ci/{cmdb_ci}",
                params={
                    "sysparm_fields": "vendor,manufacturer,support_group",
                    "sysparm_display_value": "all",
                },
            )
            ci_data = ci_resp.json().get("result", {})
            vendor_ref = ci_data.get("vendor") or ci_data.get("manufacturer")
            vendor_sys_id = extract_value(vendor_ref)
            if vendor_sys_id:
                vendor = await fetch_vendor_from_servicenow(client, vendor_sys_id, incident_number)
                set_vendor_info(incident_number, vendor)
                return vendor
        except Exception:
            log.warning("Vendor fetch from CI failed for %s", incident_number)

    # -- 2. Try assignment group's company --
    if assignment_group:
        try:
            grp_resp = await client.get(
                "/api/now/table/sys_user_group",
                params={
                    "sysparm_query": f"name={assignment_group}",
                    "sysparm_fields": "u_vendor,company",
                    "sysparm_display_value": "all",
                    "sysparm_limit": "1",
                },
            )
            grp_data = grp_resp.json().get("result", [])
            if grp_data:
                vendor_ref = grp_data[0].get("u_vendor") or grp_data[0].get("company")
                vendor_sys_id = extract_value(vendor_ref)
                if vendor_sys_id:
                    vendor = await fetch_vendor_from_servicenow(client, vendor_sys_id, incident_number)
                    set_vendor_info(incident_number, vendor)
                    return vendor
        except Exception:
            log.warning("Vendor fetch via assignment group failed for %s", incident_number)

    return None
