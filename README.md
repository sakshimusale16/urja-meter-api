# Urja Meter API

A clean, documented REST API in front of the **Urja Meter Ops** portal (`https://urja-ops.flockenergy.tech`), a legacy web portal that utility staff use to look up smart-meter data but that has no API of its own.

This service logs in to the portal, pulls the data the same way the browser does, cleans up the portal's quirks, and exposes it through simple JSON endpoints that another engineer or program can use without ever touching the portal.

- **How the portal works (my investigation):** [PROTOCOL.md](PROTOCOL.md)
- **API description (OpenAPI 3.1):** [openapi.json](openapi.json)
- **Interactive docs:** run the service and open http://127.0.0.1:8000/docs

---

## What I built

| Endpoint | What it returns |
|---|---|
| `GET /health` | Service status |
| `GET /meters` | All meters, with filters the portal doesn't offer: `status`, `make`, `phase`, `dt`, `zone`, `q` (search meter ID / serial), plus `page` and `page_size` |
| `GET /meters/{meter_id}` | One meter: nameplate details, location (lat/lng) and full network hierarchy |
| `GET /meters/{meter_id}/consumption` | 30-minute consumption readings (kWh, kVAh, voltage) with real numbers and ISO 8601 timestamps |
| `GET /transformers` | All 40 distribution transformers (DTs) |
| `GET /transformers/{code}/meters` | All meters connected to one transformer |

### Project structure

```
urja-api/
├── main.py            # FastAPI app: the clean API endpoints
├── portal_client.py   # Everything about talking to the portal
├── PROTOCOL.md        # How the portal works, as I discovered it
├── openapi.json       # Generated OpenAPI description of this API
├── requirements.txt   # Python dependencies
├── login_test.py      # Exploration script: first login from Python
├── export_test.py     # Exploration script: reproducing the signed export
└── test_client.py     # Quick manual check of portal_client.py
```

The two main files are deliberately separate:

- **`portal_client.py`** knows about cookies, login, session expiry, HMAC signatures and the portal's messy formats. If the portal changes, only this file should need to change.
- **`main.py`** only knows about clean meter and transformer data. It never sees a cookie or a signature.

The three `*_test.py` scripts are small scripts I used while learning how the portal works. I kept them because they show the investigation step by step.

---

## How to install and run

**Requirements:** Python 3.10 or newer.

```bash
# 1. Clone and enter the project
git clone <this-repo-url>
cd urja-api

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt
```

### Configure

The portal login is read from environment variables, so credentials are never stored in the code.

```powershell
# Windows PowerShell
$env:URJA_EMAIL="operator@urja.local"
$env:URJA_PASSWORD="urja-ops-2026"
```

```bash
# macOS / Linux
export URJA_EMAIL="operator@urja.local"
export URJA_PASSWORD="urja-ops-2026"
```

### Run

```bash
uvicorn main:app --reload
```

Then open **http://127.0.0.1:8000/docs** to explore and try every endpoint in the browser.

To regenerate `openapi.json` while the server is running:

```bash
curl http://127.0.0.1:8000/openapi.json -o openapi.json
```

---

## Sample requests

All faulty meters:

```bash
curl "http://127.0.0.1:8000/meters?status=Faulty"
```

```json
{
  "total": 90,
  "page": 1,
  "pageSize": 50,
  "data": [
    {
      "meterId": "J100004",
      "serialNo": "SE65293",
      "make": "Genus",
      "phaseType": "single",
      "installStatus": "Faulty",
      "installType": "CT Operated",
      "build": "v2",
      "dtCode": "DT-005",
      "hierarchy": {
        "zone": { "name": "Jaipur Zone 2", "code": "Z-02" },
        "circle": { "name": "Circle 5", "code": "C-05" },
        "...": "..."
      },
      "geo": { "lat": 26.9, "lng": 75.8 }
    }
  ]
}
```

Consumption for one meter:

```bash
curl "http://127.0.0.1:8000/meters/J100000/consumption"
```

```json
{
  "meterId": "J100000",
  "intervalMinutes": 30,
  "count": 337,
  "data": [
    { "timestamp": "2026-06-23T23:30:00", "kwh": 48438.74, "kvah": 52313.84, "voltage": 226.0 }
  ]
}
```

Other examples:

```bash
curl "http://127.0.0.1:8000/meters?make=HPL&phase=three"
curl "http://127.0.0.1:8000/meters?zone=Z-01&status=Installed"
curl "http://127.0.0.1:8000/transformers/DT-001/meters"
```

---

## How it works (short version)

Full details are in [PROTOCOL.md](PROTOCOL.md).

1. **Login:** `POST /login` with a form body (`email`, `password`). The portal sets a session cookie that lasts exactly **1 hour**.
2. **Bulk export (main data source):** the portal's "Export all meters" button calls `GET /portal/keys` to get a signing secret, then `GET /portal/export?page=1` with an **HMAC-SHA256 signature** in the `X-Signature` header. I found the signing recipe in the portal's JavaScript and reproduced it in Python. One request returns all 403 meters with location and hierarchy.
3. **Consumption:** fetched per meter from `GET /portal/meters/{id}/energy`, only when someone asks for it.
4. **Transformers:** `GET /portal/dts?page=N`, all pages combined.

---

## Assumptions

- **The export's `page=1` contains everything.** It returned `total: 403` and 403 items, so I treat it as a single page. If the portal ever split it, the client would need to loop over pages.
- **Timestamps are local time (India, UTC+05:30).** The portal shows `DD/MM/YYYY HH:mm` with no timezone, so I return ISO 8601 timestamps without a timezone offset rather than guess one.
- **Meter metadata changes rarely**, so serving it up to 10 minutes old is acceptable.
- **`Faulty`, `Installed`, `Decommissioned`** are the only install statuses (these are all I saw). Filters are case-insensitive exact matches, so unknown values simply return no results.
- **The portal is read-only for us.** The service only makes GET requests (plus the normal login).

## Design decisions and trade-offs

**Use the bulk export instead of crawling page by page.**
The alternative was 21 list pages plus about 403 detail requests per meter, where detail data comes in two different formats (`legacy` and `v2`, see PROTOCOL.md) that would each need decoding. The export gives everything in one request, already normalised into one shape. It's faster, simpler, and much lighter on the portal. The cost is that I depend on reproducing the signature correctly, which I verified.

**Cache the export in memory for 10 minutes.**
Downloading 232 kB on every API call would be slow and wasteful. The trade-off is that data can be up to 10 minutes stale. Consumption is not cached, because it is per meter and newer readings matter more.

**Re-login automatically, but only retry once.**
The session expires after 1 hour. When a request returns 401, the client logs in again and retries once. Only once, so that a wrong password produces a clear error instead of an endless loop.

**Clean the data on the way out.**
The portal sends numbers as strings (`"48438.74"`) and dates as `DD/MM/YYYY`. The API returns real numbers and ISO 8601 dates, so consumers don't inherit the portal's quirks. Missing or broken numbers become `null` instead of crashing the request.

**Check login success by the response body, not the status code.**
A failed login still returns HTTP 200, so the client checks `type == "redirect"`.

**FastAPI.**
I'm comfortable in Python, and FastAPI generates `openapi.json` and the Swagger UI automatically from the code, which keeps the documentation in sync with the API.

**Credentials in environment variables.**
Nothing secret is committed to the repository.

## What I intentionally left out

- **Automated tests.** I tested manually (scripts and Swagger UI). With limited time I prioritised understanding the portal correctly over a test suite.
- **A database.** 403 meters fit easily in memory; a database would be over-engineering at this size.
- **A web front end.** Optional, and I focused on the core API and the investigation.
- **Decoding `__data.json`.** I documented its format (devalue pointers, two builds) in PROTOCOL.md, but the export gives the same information in a cleaner form, so the API doesn't need it.

## What I'd improve with more time

- **Tests** using saved portal responses, so they run without the live portal.
- **A hierarchy endpoint** returning the full tree (Zone → Circle → Division → Subdivision → Substation → Feeder → DT → meters), with checks for inconsistent data.
- **Scale:** filtering is a simple loop over all meters in memory. This is instant for 403 meters but would struggle at hundreds of thousands. I'd then load the export into SQLite (or PostgreSQL) with indexes, and add a spatial index for "meters near this location" queries.
- **Smarter freshness:** refresh the cache in the background instead of making one user wait for the re-download.
- **Proactive re-login** a few minutes before the 1-hour session ends, rather than waiting for a 401.
- **Better OpenAPI schemas** (Pydantic response models), so the docs show the exact shape of every response.

---

## Reflection

**What assumptions did you make?**
The main ones are listed above: that the export's single page contains all meters, that timestamps are local Indian time, and that 10-minute-old meter metadata is acceptable. I also assumed the signing recipe I found in the JavaScript is stable. If the portal changed it, the export call would fail with a clear error.

**Which part was the most difficult, and how did you get unstuck?**
The bulk export. The request needed `X-Timestamp` and `X-Signature` headers, and I didn't know what was being signed. I searched the portal's JavaScript in DevTools for `X-Signature`, found the function that builds it, and read it line by line: it joins the method, path, query and timestamp with newlines and signs them with HMAC-SHA256 using a secret from `/portal/keys`. Reproducing it in Python and getting all 403 meters back confirmed I had it right.

**If you had another day, what would you improve?**
Automated tests with recorded portal responses, a hierarchy tree endpoint, and Pydantic response models so the OpenAPI docs describe every field precisely.

**What mistake did you make while solving this?**
The first time I clicked "Export all meters" I got a 401, and I assumed the export needed special permissions. In fact my session had expired. When I looked at the request headers, no cookie was being sent. That taught me to inspect the actual request before drawing conclusions from an error code, and it is how I discovered the 1-hour session limit.

**If you were reviewing your own submission, what would you criticise?**
There are no automated tests, so I can't prove it keeps working if the portal changes. The responses aren't described by strict schemas in the OpenAPI file. And the exploration scripts sit next to the main code; in a real project I'd move them into a separate folder.
