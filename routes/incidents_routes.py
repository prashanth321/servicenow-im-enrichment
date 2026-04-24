"""
Major Incidents API routes.

Provides endpoints for the Major Incidents Dashboard:
- GET /incidents/summary   — P1/P2 ongoing counts + resolved today count
- GET /incidents           — Filterable incident list (ongoing, resolved_today, historic)
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Query

from utils.api_client import ServiceNowClient
from utils.logger import get_logger

router = APIRouter(tags=["major-incidents"])
logger = get_logger(__name__)


def _map_priority(val: str | dict | None) -> str:
    """Normalise a ServiceNow priority field to '1', '2', etc."""
    if isinstance(val, dict):
        val = val.get("value") or val.get("display_value") or ""
    v = str(val or "").strip()
    # Could be "1 - Critical" or just "1"
    return v.split(" ")[0] if v else "4"


def _display(field: object) -> str:
    """Extract display_value from a SN field."""
    if isinstance(field, dict):
        return field.get("display_value") or field.get("value") or ""
    return str(field) if field else ""


def _value(field: object) -> str:
    """Extract raw value from a SN field."""
    if isinstance(field, dict):
        return field.get("value") or ""
    return str(field) if field else ""


def _build_incident(record: dict) -> dict:
    """Map a ServiceNow incident record to our dashboard model."""
    return {
        "id": _display(record.get("number")),
        "sys_id": _value(record.get("sys_id")),
        "priority": _map_priority(record.get("priority")),
        "title": _display(record.get("short_description")) or "No description",
        "team": _display(record.get("assignment_group")) or "Unassigned",
        "assigned_to": _display(record.get("assigned_to")) or "Unassigned",
        "status": _map_state(_value(record.get("state"))),
        "state_display": _display(record.get("state")),
        "cmdb_ci": _display(record.get("cmdb_ci")) or None,
        "business_impact": _display(record.get("business_impact")) or None,
        "created_at": _value(record.get("opened_at")) or None,
        "resolved_at": _value(record.get("resolved_at")) or None,
    }


def _map_state(sn_state: str) -> str:
    """Map SN numeric state to a readable status."""
    return {
        "1": "new",
        "2": "in_progress",
        "3": "on_hold",
        "6": "resolved",
        "7": "closed",
    }.get(sn_state, "unknown")


# ---------------------------------------------------------------------------
# GET /incidents/summary
# ---------------------------------------------------------------------------

@router.get("/incidents/summary")
async def incidents_summary():
    """Return counts of ongoing P1, ongoing P2, and resolved-today incidents.

    Response::

        {
            "ongoing_p1": 2,
            "ongoing_p2": 5,
            "resolved_today": 3
        }
    """
    async with ServiceNowClient() as client:
        # Ongoing P1
        p1_resp = await client.get("/api/now/table/incident", params={
            "sysparm_query": "priority=1^active=true",
            "sysparm_fields": "sys_id",
            "sysparm_limit": "100",
        })
        p1_count = len(p1_resp.json().get("result", []))

        # Ongoing P2
        p2_resp = await client.get("/api/now/table/incident", params={
            "sysparm_query": "priority=2^active=true",
            "sysparm_fields": "sys_id",
            "sysparm_limit": "100",
        })
        p2_count = len(p2_resp.json().get("result", []))

        # Resolved today — state=6 and resolved_at is today
        today = datetime.utcnow().strftime("%Y-%m-%d")
        resolved_resp = await client.get("/api/now/table/incident", params={
            "sysparm_query": (
                f"priorityIN1,2^state=6^resolved_at>={today} 00:00:00"
            ),
            "sysparm_fields": "sys_id",
            "sysparm_limit": "100",
        })
        resolved_count = len(resolved_resp.json().get("result", []))

    return {
        "ongoing_p1": p1_count,
        "ongoing_p2": p2_count,
        "resolved_today": resolved_count,
    }


# ---------------------------------------------------------------------------
# GET /incidents?status=ongoing|resolved_today|historic
# ---------------------------------------------------------------------------

_FIELDS = (
    "sys_id,number,priority,short_description,assignment_group,"
    "assigned_to,state,opened_at,resolved_at,cmdb_ci,business_impact"
)


@router.get("/incidents")
async def list_incidents(status: str = Query("ongoing", pattern="^(ongoing|resolved_today|historic)$")):
    """Return a filtered list of major incidents (P1/P2).

    Query params:
        status: 'ongoing' | 'resolved_today' | 'historic'
    """
    today = datetime.utcnow().strftime("%Y-%m-%d")

    if status == "ongoing":
        query = "priorityIN1,2^active=true^ORDERBYpriority^ORDERBYDESCopened_at"
    elif status == "resolved_today":
        query = f"priorityIN1,2^state=6^resolved_at>={today} 00:00:00^ORDERBYDESCresolved_at"
    else:  # historic
        query = "priorityIN1,2^stateIN6,7^ORDERBYDESCresolved_at"

    async with ServiceNowClient() as client:
        response = await client.get("/api/now/table/incident", params={
            "sysparm_query": query,
            "sysparm_fields": _FIELDS,
            "sysparm_display_value": "all",
            "sysparm_limit": "50",
        })

    results = response.json().get("result", [])
    return [_build_incident(r) for r in results]


# ---------------------------------------------------------------------------
# GET /support-groups — dropdown list of assignment groups
# ---------------------------------------------------------------------------

@router.get("/support-groups")
async def list_support_groups():
    """Return distinct support/assignment groups from ServiceNow.

    Response::

        [{"sys_id": "...", "name": "Network"}, ...]
    """
    async with ServiceNowClient() as client:
        response = await client.get("/api/now/table/sys_user_group", params={
            "sysparm_query": "active=true^ORDERBYname",
            "sysparm_fields": "sys_id,name",
            "sysparm_display_value": "true",
            "sysparm_limit": "200",
        })
    results = response.json().get("result", [])
    return [{"sys_id": r.get("sys_id", ""), "name": r.get("name", "")} for r in results]


# ---------------------------------------------------------------------------
# GET /oncall?group_id=<sys_id> — who is on call for a support group
# ---------------------------------------------------------------------------

@router.get("/oncall")
async def get_oncall(group_id: str = Query(..., description="sys_id of the support group")):
    """Return on-call users for the given support group.

    Response::

        {
            "group_name": "Network",
            "users": [
                {"name": "...", "email": "...", "phone": "...", "userId": "..."}
            ]
        }
    """
    async with ServiceNowClient() as client:
        # Get group name
        grp_resp = await client.get("/api/now/table/sys_user_group", params={
            "sysparm_query": f"sys_id={group_id}",
            "sysparm_fields": "name",
            "sysparm_limit": "1",
        })
        grp_results = grp_resp.json().get("result", [])
        group_name = grp_results[0].get("name", "Unknown") if grp_results else "Unknown"

        # Fetch on-call rota
        try:
            oncall_resp = await client.get(
                "/api/now/on_call_rota/whoisoncall",
                params={"group_sys_id": group_id},
            )
            oncall_data = oncall_resp.json().get("result", [])
        except Exception:
            oncall_data = []

        # If on_call_rota API returned nothing, fall back to group members
        users = []
        if isinstance(oncall_data, list) and oncall_data:
            for u in oncall_data:
                user_id = u.get("userId") or u.get("user", {}).get("value", "")
                users.append({
                    "name": u.get("name") or u.get("user", {}).get("display_value", "Unknown"),
                    "email": u.get("email", ""),
                    "phone": u.get("phone", ""),
                    "userId": user_id,
                })
        elif isinstance(oncall_data, dict):
            raw_users = oncall_data.get("users", [])
            for u in raw_users:
                users.append({
                    "name": u.get("name", "Unknown"),
                    "email": u.get("email", ""),
                    "phone": u.get("phone", ""),
                    "userId": u.get("userId", ""),
                })

        # Fallback: fetch group members if rota returned nothing
        if not users:
            members_resp = await client.get("/api/now/table/sys_user_grmember", params={
                "sysparm_query": f"group={group_id}",
                "sysparm_fields": "user",
                "sysparm_display_value": "all",
                "sysparm_limit": "20",
            })
            members = members_resp.json().get("result", [])
            user_sys_ids = []
            for m in members:
                uid = m.get("user", {})
                if isinstance(uid, dict):
                    user_sys_ids.append(uid.get("value", ""))
                else:
                    user_sys_ids.append(str(uid))

            if user_sys_ids:
                ids_str = ",".join(user_sys_ids)
                users_resp = await client.get("/api/now/table/sys_user", params={
                    "sysparm_query": f"sys_idIN{ids_str}",
                    "sysparm_fields": "sys_id,name,email,phone",
                    "sysparm_limit": "20",
                })
                for u in users_resp.json().get("result", []):
                    users.append({
                        "name": u.get("name", "Unknown"),
                        "email": u.get("email", ""),
                        "phone": u.get("phone", ""),
                        "userId": u.get("sys_id", ""),
                    })

    return {"group_name": group_name, "users": users}
