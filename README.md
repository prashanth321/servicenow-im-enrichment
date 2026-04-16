# ServiceNow Incident Management Enrichment Service

A production-ready Python service that listens for ServiceNow P2 incident events (via webhook or polling), enriches them with CMDB/CI data, on-call details, business application metadata, and business impact — then writes the enriched data back to the incident record.

## Architecture

```
┌──────────────┐    POST /webhook     ┌────────────────────┐
│  ServiceNow  │ ──────────────────▶  │    FastAPI App      │
│  Business    │                      │                    │
│  Rule / REST │                      │  ┌──────────────┐  │
│  Message     │                      │  │ Enrichment   │  │
└──────────────┘                      │  │ Pipeline     │  │
                                      │  └──────┬───────┘  │
                                      │         │          │
┌──────────────┐   Polling loop       │  ┌──────▼───────┐  │
│  ServiceNow  │ ◀──── asyncio ──── │  │ 1. CMDB CI   │  │
│  Incident    │                      │  │ 2. On-Call   │  │
│  Table       │ ◀──── PATCH ──────── │  │ 3. Biz App   │  │
└──────────────┘                      │  │ 4. Impact    │  │
                                      │  │ 5. Update    │  │
                                      │  └──────────────┘  │
                                      └────────────────────┘
```

## Project Structure

```
servicenow-im-enrichment/
├── main.py                        # FastAPI app + webhook + polling
├── config/
│   └── settings.py                # Pydantic BaseSettings — loads .env
├── services/
│   ├── incident_service.py        # Fetch & update SN incidents
│   ├── cmdb_service.py            # Fetch CI data from CMDB
│   ├── oncall_service.py          # Fetch on-call and escalation contacts
│   ├── app_service.py             # Fetch Business Application details
│   └── impact_service.py          # Derive business impact from tier/criticality
├── utils/
│   ├── api_client.py              # httpx async client with auth, retry, timeout
│   ├── exceptions.py              # Custom exception classes
│   └── logger.py                  # JSON structured logger setup
├── models/
│   └── schemas.py                 # Pydantic models for request/response payloads
├── .env.example
├── requirements.txt
└── README.md
```

## Prerequisites

- Python 3.11+
- A ServiceNow instance with:
  - A user account with read/write access to the `incident`, `cmdb_ci`, `cmdb_ci_business_app`, and `on_call_rota` tables
  - (Optional) A Business Rule or outbound REST Message configured to POST to the `/webhook` endpoint

## Setup & Installation

```bash
# Clone the repository
git clone <repo-url>
cd servicenow-im-enrichment

# Create a virtual environment
python -m venv .venv

# Activate it
# Windows:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create your environment file
cp .env.example .env
# Edit .env with your ServiceNow instance details
```

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `SN_BASE_URL` | Base URL of your ServiceNow instance (e.g. `https://dev12345.service-now.com`) | **required** |
| `SN_USERNAME` | ServiceNow API username | **required** |
| `SN_PASSWORD` | ServiceNow API password | **required** |
| `PORT` | Port the FastAPI server listens on | `3000` |
| `POLLING_INTERVAL_SECONDS` | Seconds between polling cycles | `60` |
| `LOG_LEVEL` | Python log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |

## Running the Service

### Webhook + Polling Mode (default)

Both the webhook endpoint and the background polling loop run together:

```bash
python main.py
```

Or with uvicorn directly:

```bash
uvicorn main:app --host 0.0.0.0 --port 3000
```

The service will:
- Listen for `POST /webhook` requests on port 3000
- Run a background polling loop every 60 seconds (configurable)

### Webhook-Only Mode

If you only need the webhook (no polling), you can remove or disable the polling task in `main.py` lifespan. For most deployments, running both is recommended.

## Testing with curl

### Health Check

```bash
curl http://localhost:3000/health
```

Response:
```json
{"status": "ok"}
```

### Send a Webhook (P2 Incident)

```bash
curl -X POST http://localhost:3000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "sys_id": "a1b2c3d4e5f67890a1b2c3d4e5f67890",
    "number": "INC0012345",
    "priority": "2",
    "cmdb_ci": "abc123def456789abc123def456789ab",
    "short_description": "Payment gateway timeout causing order failures",
    "assignment_group": "xyz789abc123def456789abc123def456"
  }'
```

Success response:
```json
{
  "status": "enriched",
  "incident": "INC0012345",
  "enrichment_status": "complete",
  "business_impact": "High"
}
```

### Send a Webhook (Non-P2 — skipped)

```bash
curl -X POST http://localhost:3000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "sys_id": "a1b2c3d4e5f67890a1b2c3d4e5f67890",
    "number": "INC0067890",
    "priority": "3",
    "short_description": "Low priority issue"
  }'
```

Response:
```json
{"status": "skipped", "message": "Priority 3 is not P2"}
```

## Example Payloads

### Inbound Webhook Payload

```json
{
  "sys_id": "a1b2c3d4e5f67890a1b2c3d4e5f67890",
  "number": "INC0012345",
  "priority": "2",
  "cmdb_ci": "abc123def456789abc123def456789ab",
  "short_description": "Payment gateway timeout causing order failures",
  "assignment_group": "xyz789abc123def456789abc123def456"
}
```

### Enriched Incident Update (PATCH body sent to ServiceNow)

```json
{
  "business_impact": "High",
  "application_owner": "Jane Smith",
  "u_technical_owner": "Bob Johnson",
  "support_group": "Payment Platform Support",
  "work_notes": "=== Automated Enrichment Summary ===\nIncident: INC0012345\nBusiness Impact: High\nEnrichment Status: complete\nCI Name: payment-gateway-prod\nBusiness Application: Payment Platform\nService Mapping: Tier 1\nSupport Group (CMDB): Payment Platform Support\nOn-Call: Alice Wong (alice.wong@example.com)\nEscalation Contacts: Carlos Reyes, Dana Patel\nApplication Owner: Jane Smith\nTechnical Owner: Bob Johnson\nContact Email: payment-platform@example.com\n=== End Enrichment ==="
}
```

## Enrichment Pipeline

1. **Webhook / Polling** — Receive or discover P2 incidents
2. **CMDB Lookup** — Fetch CI name, business app, service mapping, support group
3. **On-Call Lookup** — Find who is on-call for the support group + escalation chain
4. **App Lookup** — Get application owner, technical owner, contact email
5. **Impact Derivation** — Determine High / Medium / Low from tier + criticality
6. **Incident Update** — PATCH all enriched fields + work_notes back to ServiceNow

If any step fails, the service continues with partial enrichment and marks the status accordingly.

## Error Handling

- **CI not found**: Warning logged, enrichment continues without CI data
- **API failures after retries**: Error logged with incident number, enrichment marked as `"partial"`
- **Individual incident failure**: Logged and skipped — never crashes the service or polling loop
- **Retry logic**: 3 attempts with exponential back-off on HTTP 429, 500, 503, and network errors

## Logging

All logs are JSON-structured (via `python-json-logger`) and written to stdout. Every log line includes:
- `timestamp`
- `level`
- `incident_number` (when available)
- `message`

Example:
```json
{"timestamp": "2025-01-15T10:30:00.123Z", "level": "INFO", "incident_number": "INC0012345", "message": "CI details fetched successfully"}
```

## License

MIT
