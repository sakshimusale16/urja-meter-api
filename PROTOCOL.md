PROTOCOL.md

# Urja Meter Ops — Portal Protocol Notes

How the portal at `https://urja-ops.flockenergy.tech` works under the hood, as discovered with browser DevTools (Network, Elements and Sources tabs).

## 1. Technology
- Front end built with **SvelteKit** (seen as `data-sveltekit-preload-data="hover"` on `<body>`).
- Authentication uses the **Better Auth** library (cookie name prefix `better-auth`).
- Pages: **Meters**, **Meter detail** (`/meters/{meterId}`), **Transformers**.
- "Ops Desk" in the header is the logged-in user's display name (a `<span>`), not a page.

## 2. Login / Auth
- `POST /login`
- Body: `application/x-www-form-urlencoded` with fields `email`, `password`.
- Send an `Origin: https://urja-ops.flockenergy.tech` header (SvelteKit rejects cross-origin form posts — CSRF protection).
- Response is a SvelteKit form-action result, always HTTP **200**:
  - Success: `{ "type": "redirect", "status": 303, "location": "/meters" }`
  - Failure: HTTP is still 200, so check the `type` field, not the HTTP status. (Quirk.)
- Success sets cookie `__Secure-better-auth.session_token` with `Max-Age=3600; Path=/; HttpOnly; Secure; SameSite=Lax`.
- Every later request sends that cookie.

## 3. Session expiry
- Session lasts **1 hour** (`Max-Age=3600`), confirmed by testing.
- After expiry:
  - JSON calls (e.g. `/portal/keys`) return **401 Unauthorized**.
  - Page visits (e.g. `/transformers`) return **302** redirect to `/login`.
- The API service must detect this and log in again automatically.

## 4. Meters

### Meter list (paginated)
- `GET /portal/meters/search?q=&page=1` → JSON
  - `q` = search text (meter number or serial), `page` = page number
- Response: `{ data: [...], page: 1, pageSize: 20, total: 403 }`
- 403 meters → 21 pages.

Fields per meter in the list:

| Field | Example | Meaning |
|---|---|---|
| meterId | J100000 | Meter number |
| serialNo | SE33962 | Serial number |
| make | HPL | Manufacturer |
| phaseType | single | Single- or three-phase |
| installStatus | Decommissioned | Installed / Faulty / Decommissioned |
| dtCode | DT-001 | Distribution transformer the meter is connected to |

### Location
- `GET /portal/meters/{meterId}/geo`
- Response: `{ data: { latitude: "26.93...", longitude: "75.83..." } }` — values are **strings**.

### Consumption
- `GET /portal/meters/{meterId}/energy`
- Response: `{ data: [ { timestamp, kwh, kvah, voltR } ] }`
- Readings every **30 minutes**; latest reading seen 30/06/2026 23:30.
- Numbers are **strings** (`"48438.74"`).
- Timestamp format is `DD/MM/YYYY HH:mm` (ambiguous; should be converted to ISO 8601).

### Meter detail page data (SvelteKit)
- `GET /meters/{meterId}/__data.json?x-sveltekit-invalidated=001`
- Response header: `Cache-Control: private, no-store`.
- Returns `{ type: "data", nodes: [...] }`:
  - nodes 0 and 1 are `"skip"` (layout layers already loaded).
  - node 2 is the page data.
- node 2 uses SvelteKit's **devalue** format: one flat array where numbers are **index pointers** to other positions (repeated values are stored once and referenced). Must be decoded in code.
- Top object: `{ meterId, detail, hierarchy }` (all pointers).
- Extra field not in the list endpoint: **Installation Type** (e.g. "Whole Current").
- Hierarchy keys have spaces: `Zone, Circle, Division, Subdivision, Sub Station, Feeder, DT`.
- Hierarchy values include codes in brackets, e.g. `"Circle 1 (C-01)"`, `"Malviya Nagar DT 1 (DT-001)"`.

### Two meter "builds" (messy data)
Each meter has `build` = `"legacy"` or `"v2"`. They differ in `__data.json`:
- **legacy**: `detail = { data: [...] }`, a list of `{ parameterName, parameterValue }` pairs (e.g. "Meter ID", "Serial No").
- **v2**: `detail = { classData: "<JSON string>" }` — JSON stored as text (double-encoded), keys in PascalCase inside `installed_meter` (e.g. `MeterId`, `SerialNo`).
- Hierarchy format is the same for both.
- geo and energy endpoints look the same for both builds.

### Quirk: hover preloading
- Hovering over a meter link makes SvelteKit fetch that meter's `__data.json` in advance.
- So the Network log can show requests for meters that were never clicked.

## 5. Network hierarchy
Zone → Circle → Division → Subdivision → Substation → Feeder → DT (transformer) → Meter

Example (J100000): Jaipur Zone 1 (Z-01) → Circle 1 (C-01) → Division 1 (D-01) → Subdivision 1 (SD-01) → Substation 1 (SS-01) → Feeder 1 (F-001) → Malviya Nagar DT 1 (DT-001).

## 6. Transformers (DTs)
- `GET /portal/dts?page=1` → `{ data, page, pageSize: 20, total: 40 }` (2 pages)
- Fields: `code`, `name`, `feederCode`, `capacityKva`
- Quirk: `capacityKva` is a **number** here, while energy values are **strings**.
- Each DT links to a feeder (e.g. DT-001 → F-001).

## 7. Bulk export (best data source)
Triggered by the "Export all meters" button on the Transformers page.

Flow:
1. `GET /portal/keys` → `{ data: { signingSecret } }` (requires a valid session; returns 401 otherwise).
2. `GET /portal/export?page=1` with headers:
   - `X-Timestamp`: current Unix time in seconds
   - `X-Signature`: signature (see recipe below)
- Returns **all 403 meters in one response**: `{ data: [...], total: 403 }` (~232 kB).
- Downloaded by the browser as a `.json` file.

### Signature recipe
Found in `/_app/immutable/nodes/4.*.js`, function `C(method, path, query, secret)`:
- `timestamp` = Unix time in seconds, as a string
- `message` = `METHOD + "\n" + PATH + "\n" + QUERY + "\n" + timestamp`
  - e.g. `GET\n/portal/export\npage=1\n1792692177`
- `signature` = lowercase hex of **HMAC-SHA256**(key = signingSecret, message)
- Verified: Python reproduction returns 200 with all 403 meters

### Export item fields
`meterId, serialNo, make, phaseType, installStatus, installType, dtCode, build, geo: { lat, lng }, hierarchy: { zone, circle, division, subdivision, substation, feeder, dt }` — each hierarchy level is `{ name, code }`.

### Export quirks
- `geo` values are **numbers** here but **strings** in `/geo`.
- Export hierarchy is already clean (name and code separated), unlike `__data.json`.
- Export normalises both `legacy` and `v2` builds into one shape.
- The export does not include consumption; that still comes from `/energy` per meter.
- Do not store `signingSecret`; fetch it fresh each time.

## 8. Summary of quirks
1. Failed login still returns HTTP 200; check the `type` field.
2. Session expires after exactly 1 hour.
3. Numbers sometimes strings (energy, geo), sometimes numbers (capacityKva, export geo).
4. Dates in `DD/MM/YYYY HH:mm`.
5. Hover preloading triggers requests for unclicked meters.
6. `__data.json` uses devalue pointer encoding.
7. Two meter builds with different detail formats (legacy vs v2 double-encoded JSON).
8. Inconsistent naming: "Sub Station" vs "Substation", keys with spaces.
9. Bulk export requires an HMAC-signed request.