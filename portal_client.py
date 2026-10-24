"""Client for the Urja Meter Ops portal.

Handles login, automatic re-login when the 1-hour session expires,
the HMAC-signed bulk export, and cleaning up messy portal data.
"""
import hashlib
import hmac
import os
import time
from datetime import datetime

import requests

BASE_URL = "https://urja-ops.flockenergy.tech"
EXPORT_CACHE_SECONDS = 600  # re-fetch the bulk export after 10 minutes


class PortalError(Exception):
    """Raised when the portal returns something we can't handle."""


def _to_float(value):
    """Portal sends numbers as strings; return None if a value is missing or bad."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class PortalClient:
    def __init__(self, email=None, password=None, base_url=BASE_URL):
        self.base_url = base_url
        self.email = email or os.environ["URJA_EMAIL"]
        self.password = password or os.environ["URJA_PASSWORD"]
        self.session = requests.Session()
        self._logged_in = False
        self._export_cache = None
        self._export_fetched_at = 0.0

    # ---------- auth ----------
    def login(self):
        resp = self.session.post(
            f"{self.base_url}/login",
            data={"email": self.email, "password": self.password},
            headers={"Origin": self.base_url, "Accept": "application/json",
                     "x-sveltekit-action": "true"},
            timeout=15,
        )
        # Quirk: HTTP is 200 even when login fails, so check the "type" field.
        if resp.json().get("type") != "redirect":
            raise PortalError("Login failed: check URJA_EMAIL / URJA_PASSWORD")
        self._logged_in = True

    def _get(self, path, params=None, headers=None):
        """GET a portal JSON endpoint; log in again once if the session expired."""
        if not self._logged_in:
            self.login()
        for attempt in range(2):
            resp = self.session.get(f"{self.base_url}{path}", params=params,
                                    headers=headers, timeout=30)
            if resp.status_code == 401 and attempt == 0:
                self.login()  # 1-hour cookie expired -> log in and retry once
                continue
            if resp.status_code != 200:
                raise PortalError(f"{path} returned HTTP {resp.status_code}")
            return resp.json()

    # ---------- bulk export ----------
    def _signed_headers(self, secret, path, query):
        timestamp = str(int(time.time()))
        message = "\n".join(["GET", path, query, timestamp])
        signature = hmac.new(secret.encode(), message.encode(),
                             hashlib.sha256).hexdigest()
        return {"X-Timestamp": timestamp, "X-Signature": signature}

    def get_all_meters(self):
        """All meters from the signed bulk export, cached for 10 minutes."""
        fresh = time.time() - self._export_fetched_at < EXPORT_CACHE_SECONDS
        if self._export_cache is not None and fresh:
            return self._export_cache
        secret = self._get("/portal/keys")["data"]["signingSecret"]
        headers = self._signed_headers(secret, "/portal/export", "page=1")
        data = self._get("/portal/export", params={"page": 1}, headers=headers)
        self._export_cache = data["data"]
        self._export_fetched_at = time.time()
        return self._export_cache

    # ---------- transformers ----------
    def get_transformers(self):
        """All DTs, walking through every page."""
        items, page = [], 1
        while True:
            data = self._get("/portal/dts", params={"page": page})
            items.extend(data["data"])
            if len(items) >= data["total"] or not data["data"]:
                return items
            page += 1

    # ---------- consumption ----------
    def get_consumption(self, meter_id):
        """30-minute readings with real numbers and ISO timestamps."""
        data = self._get(f"/portal/meters/{meter_id}/energy")
        return [
            {
                # Quirk: portal uses "DD/MM/YYYY HH:mm" and string numbers.
                "timestamp": datetime.strptime(
                    r["timestamp"], "%d/%m/%Y %H:%M").isoformat(),
                "kwh": _to_float(r.get("kwh")),
                "kvah": _to_float(r.get("kvah")),
                "voltage": _to_float(r.get("voltR")),
            }
            for r in data["data"]
        ]