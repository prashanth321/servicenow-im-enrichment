"""Quick script to fetch active incidents from the ServiceNow dev instance."""
import asyncio
import sys
sys.path.insert(0, ".")

from config.settings import settings
from utils.api_client import ServiceNowClient


async def fetch():
    async with ServiceNowClient() as client:
        resp = await client.get("/api/now/table/incident", params={
            "sysparm_query": "active=true^ORDERBYDESCpriority",
            "sysparm_fields": "number,priority,state,short_description,cmdb_ci,assignment_group,opened_at,assigned_to",
            "sysparm_limit": "25",
            "sysparm_display_value": "true",
        })
        results = resp.json().get("result", [])
        print(f"=== Active Incidents from {settings.sn_base_url} ===")
        print(f"Total: {len(results)}\n")
        header = f"{'Number':<14} {'Priority':<12} {'State':<14} {'Opened':<22} {'Short Description'}"
        print(header)
        print("-" * len(header))
        for inc in results:
            num = inc.get("number", "")
            pri = inc.get("priority", "")
            st = inc.get("state", "")
            opened = (inc.get("opened_at", "") or "")[:19]
            desc = (inc.get("short_description", "") or "N/A")[:50]
            print(f"{num:<14} {pri:<12} {st:<14} {opened:<22} {desc}")


asyncio.run(fetch())
