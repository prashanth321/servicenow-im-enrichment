"""
Vendor information service.

Manages vendor contact details, support hours, and SLA terms associated
with incidents. Fetches vendor data from ServiceNow's vendor table when
available, with a fallback to in-memory storage.

Converted from VendorPanel.tsx.
"""

from __future__ import annotations

from models.dashboard_schemas import VendorInfo, VendorSLA, VendorSupportHours
from utils.api_client import ServiceNowClient
from utils.exceptions import ServiceNowAPIError
from utils.logger import get_logger

# In-memory store: incident_number -> VendorInfo
_vendor_store: dict[str, VendorInfo] = {}

logger = get_logger(__name__)


def _default_vendor() -> VendorInfo:
    """Return a default vendor template (matching the React mock data)."""
    return VendorInfo(
        vendor_name="CloudTech Solutions",
        account_manager="Sarah Chen",
        support_email="support@cloudtech.example.com",
        support_phone="+1 (555) 100-2000",
        emergency_line="+1 (555) 100-9999",
        support_hours=VendorSupportHours(
            weekday="8:00 AM – 8:00 PM EST",
            weekend="10:00 AM – 4:00 PM EST",
            holiday="Emergency only",
            emergency="24/7 via emergency line",
        ),
        sla_terms=[
            VendorSLA(priority="P1", response_time="15 minutes", resolution_time="4 hours"),
            VendorSLA(priority="P2", response_time="30 minutes", resolution_time="8 hours"),
        ],
        uptime_guarantee="99.95%",
        contract_expiry="2027-03-31",
    )


def get_vendor_info(incident_number: str) -> VendorInfo:
    """Return vendor info for an incident, using defaults if not set."""
    if incident_number not in _vendor_store:
        _vendor_store[incident_number] = _default_vendor()
    return _vendor_store[incident_number]


def set_vendor_info(incident_number: str, vendor: VendorInfo) -> VendorInfo:
    """Set or update vendor info for an incident."""
    _vendor_store[incident_number] = vendor
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
