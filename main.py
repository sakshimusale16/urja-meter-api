"""Urja Meter API: a clean REST API over the Urja Meter Ops portal."""
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from portal_client import PortalClient, PortalError

app = FastAPI(
    title="Urja Meter API",
    description="Clean, documented access to smart-meter data from the Urja Meter Ops portal.",
    version="1.0.0",
)
client = PortalClient()


def _find_meter(meter_id: str) -> dict:
    for meter in client.get_all_meters():
        if meter["meterId"].lower() == meter_id.lower():
            return meter
    raise HTTPException(status_code=404, detail=f"Meter {meter_id} not found")


@app.get("/health", tags=["system"])
def health():
    """Check that the service is running."""
    return {"status": "ok"}


@app.get("/meters", tags=["meters"])
def list_meters(
    status: Optional[str] = Query(None, description="e.g. Installed, Faulty, Decommissioned"),
    make: Optional[str] = Query(None, description="Manufacturer, e.g. HPL"),
    phase: Optional[str] = Query(None, description="single or three"),
    dt: Optional[str] = Query(None, description="Transformer code, e.g. DT-001"),
    zone: Optional[str] = Query(None, description="Zone code, e.g. Z-01"),
    q: Optional[str] = Query(None, description="Search in meter ID or serial number"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    """List meters, with filters the original portal does not offer."""
    meters = client.get_all_meters()

    def matches(m):
        return all([
            not status or m["installStatus"].lower() == status.lower(),
            not make or m["make"].lower() == make.lower(),
            not phase or m["phaseType"].lower() == phase.lower(),
            not dt or m["dtCode"].lower() == dt.lower(),
            not zone or m["hierarchy"]["zone"]["code"].lower() == zone.lower(),
            not q or q.lower() in m["meterId"].lower() or q.lower() in m["serialNo"].lower(),
        ])

    filtered = [m for m in meters if matches(m)]
    start = (page - 1) * page_size
    return {"total": len(filtered), "page": page, "pageSize": page_size,
            "data": filtered[start:start + page_size]}


@app.get("/meters/{meter_id}", tags=["meters"])
def get_meter(meter_id: str):
    """Full details of one meter, including location and network hierarchy."""
    return _find_meter(meter_id)


@app.get("/meters/{meter_id}/consumption", tags=["meters"])
def get_meter_consumption(meter_id: str):
    """30-minute consumption readings for one meter."""
    meter = _find_meter(meter_id)
    try:
        readings = client.get_consumption(meter["meterId"])
    except PortalError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"meterId": meter["meterId"], "intervalMinutes": 30,
            "count": len(readings), "data": readings}


@app.get("/transformers", tags=["transformers"])
def list_transformers():
    """All distribution transformers (DTs)."""
    data = client.get_transformers()
    return {"total": len(data), "data": data}


@app.get("/transformers/{code}/meters", tags=["transformers"])
def transformer_meters(code: str):
    """All meters connected to one transformer."""
    meters = [m for m in client.get_all_meters() if m["dtCode"].lower() == code.lower()]
    return {"dtCode": code.upper(), "total": len(meters), "data": meters}