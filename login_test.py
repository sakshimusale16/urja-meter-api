import os
import requests

BASE = "https://urja-ops.flockenergy.tech"

session = requests.Session()   # remembers cookies, like a browser

resp = session.post(
    f"{BASE}/login",
    data={"email": os.environ["URJA_EMAIL"],
          "password": os.environ["URJA_PASSWORD"]},
    headers={"Origin": BASE, "Accept": "application/json",
             "x-sveltekit-action": "true"},
)
print("Login reply:", resp.json())

r = session.get(f"{BASE}/portal/meters/search", params={"q": "", "page": 1})
print("Status:", r.status_code, "| Total meters:", r.json()["total"])
