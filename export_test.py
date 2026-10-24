import hashlib
import hmac
import os
import time
import requests

BASE = "https://urja-ops.flockenergy.tech"
session = requests.Session()

# 1. Log in (same as before)
session.post(
    f"{BASE}/login",
    data={"email": os.environ["URJA_EMAIL"],
          "password": os.environ["URJA_PASSWORD"]},
    headers={"Origin": BASE, "Accept": "application/json",
             "x-sveltekit-action": "true"},
)

# 2. Get the signing secret
secret = session.get(f"{BASE}/portal/keys").json()["data"]["signingSecret"]

# 3. Build and sign the message (the recipe from function C)
timestamp = str(int(time.time()))
message = "\n".join(["GET", "/portal/export", "page=1", timestamp])
signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

# 4. Call the export with the signature headers
r = session.get(
    f"{BASE}/portal/export",
    params={"page": 1},
    headers={"X-Timestamp": timestamp, "X-Signature": signature},
)
data = r.json()
print("Status:", r.status_code, "| Total:", data["total"], "| Got:", len(data["data"]))
print("First meter:", data["data"][0])
