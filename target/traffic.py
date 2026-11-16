"""Generates the recorded-traffic inputs the problem statement says teams receive:

  inputs/har.json          normal user journeys recorded through a proxy (HAR-like JSON)
  inputs/access_log.jsonl  ~120 days of API-gateway access logs

Recorded from a CLEAN instance (no defects), as production traffic would be.
Run:  python -m target.traffic
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from target.app import State, serve

ROOT = Path(__file__).resolve().parents[1]
ACCOUNTS = {"goa.admin": "Sandbox#Goa1", "goa.sub": "Sandbox#Goa2", "delhi.admin": "Sandbox#Del1", "delhi.sub": "Sandbox#Del2"}
TRAVELLERS = [[{"name": "Ananya Rao", "passport": "Z4829173"}], [{"name": "Vikram Sethi", "passport": "N7712038"}, {"name": "Ira Sethi", "passport": "N7712039"}]]


class Recorder:
    def __init__(self, base: str):
        self.c = httpx.Client(base_url=base, timeout=5)
        self.sessions: list[dict] = []

    def journey(self, user: str, name: str):
        rec = self
        sess = {"journey": name, "entries": []}
        self.sessions.append(sess)

        class J:
            tok = None

            def call(self, method, url, body=None):
                headers = {"Authorization": f"Bearer {self.tok}"} if self.tok else {}
                r = rec.c.request(method, url, json=body, headers=headers)
                parts = urlsplit(url)
                try:
                    resp = r.json()
                except Exception:
                    resp = r.text
                sess["entries"].append({"method": method, "path": parts.path, "query": parts.query, "auth": bool(self.tok), "request_headers": headers,
                                        "request_body": body, "status": r.status_code, "response_body": resp})
                return resp

        j = J()
        j.tok = j.call("POST", "/api/v3/auth/login", {"username": user, "password": ACCOUNTS[user]})["token"]
        return j


def record_har(base: str) -> list[dict]:
    R = Recorder(base)
    for user, city, hotel, room, coupon, trav in [("goa.sub", "Goa", "H101", "DLX", None, 0), ("delhi.sub", "Dubai", "H201", "DLX", "MONSOON5", 1)]:
        j = R.journey(user, "search-quote-book-pay-docs")
        j.call("GET", f"/api/v3/hotels/search?city={city}")
        j.call("GET", f"/api/v3/hotels/{hotel}")
        q = j.call("POST", "/api/v3/quotes", {"hotel_id": hotel, "room_code": room, "nights": 3, "rooms": 1, "coupon": coupon})
        b = j.call("POST", "/api/v3/bookings", {"quote_id": q["quote_id"], "travellers": TRAVELLERS[trav], "contact_email": f"{user}@agency.example"})
        j.call("POST", f"/api/v3/bookings/{b['booking_id']}/pay")
        j.call("GET", f"/api/v3/bookings/{b['booking_id']}")
        j.call("GET", f"/api/v3/bookings/{b['booking_id']}/voucher")
        j.call("GET", f"/api/v3/invoices/{b['booking_id']}")
        j.call("GET", "/api/v3/wallet")

    j = R.journey("goa.admin", "book-pay-cancel-refund")
    q = j.call("POST", "/api/v3/quotes", {"hotel_id": "H302", "room_code": "STD", "nights": 2, "rooms": 1})
    b = j.call("POST", "/api/v3/bookings", {"quote_id": q["quote_id"], "travellers": TRAVELLERS[0], "contact_email": "ops@goagetaways.example"})
    j.call("POST", f"/api/v3/bookings/{b['booking_id']}/pay")
    j.call("POST", f"/api/v3/bookings/{b['booking_id']}/cancel")
    j.call("GET", f"/api/v3/bookings/{b['booking_id']}")
    j.call("GET", "/api/v3/wallet")

    j = R.journey("delhi.admin", "hold-then-release")
    q = j.call("POST", "/api/v3/quotes", {"hotel_id": "H401", "room_code": "DLX", "nights": 1, "rooms": 2})
    b = j.call("POST", "/api/v3/bookings", {"quote_id": q["quote_id"], "travellers": TRAVELLERS[1], "contact_email": "desk@delhidarshan.example"})
    j.call("POST", f"/api/v3/bookings/{b['booking_id']}/cancel")
    j.call("GET", "/api/v3/bookings")

    j = R.journey("goa.sub", "welcome-coupon")
    j.call("POST", "/api/v3/quotes", {"hotel_id": "H102", "room_code": "STD", "nights": 2, "rooms": 1, "coupon": "WELCOME10"})
    j.call("POST", "/api/v3/quotes", {"hotel_id": "H102", "room_code": "STD", "nights": 3, "rooms": 1, "coupon": "WELCOME10"})

    j = R.journey("delhi.sub", "profile")
    j.call("GET", "/api/v3/me")
    j.call("PATCH", "/api/v3/me", {"display_name": "Arjun K (Delhi Darshan)", "phone": "+91-90000-00044"})

    j = R.journey("goa.admin", "agency-admin")
    j.call("GET", "/api/v3/agency/markup")
    j.call("PUT", "/api/v3/agency/markup", {"percent": 9})
    j.call("GET", "/api/v3/agency/markup")
    j.call("GET", "/api/v3/agency/users")
    j.call("PUT", "/api/v3/agency/markup", {"percent": 8})
    return R.sessions


def access_logs(days: int = 120, seed: int = 7) -> list[dict]:
    rnd = random.Random(seed)
    now = time.time()
    routes = [  # (template, method, client, daily volume)
        ("/api/v3/auth/login", "POST", "portal", 60), ("/api/v3/hotels/search", "GET", "portal", 400),
        ("/api/v3/hotels/{h}", "GET", "portal", 220), ("/api/v3/quotes", "POST", "portal", 140),
        ("/api/v3/bookings", "POST", "portal", 45), ("/api/v3/bookings/{b}/pay", "POST", "portal", 40),
        ("/api/v3/bookings/{b}", "GET", "portal", 120), ("/api/v3/bookings/{b}/cancel", "POST", "portal", 6),
        ("/api/v3/bookings/{b}/voucher", "GET", "portal", 35), ("/api/v3/invoices/{b}", "GET", "portal", 25),
        ("/api/v3/bookings", "GET", "portal", 50), ("/api/v3/wallet", "GET", "portal", 70),
        ("/api/v3/me", "GET", "portal", 60), ("/api/v3/me", "PATCH", "portal", 1),
        ("/api/v3/agency/markup", "GET", "portal", 4), ("/api/v3/agency/markup", "PUT", "portal", 0.3),
        ("/api/v3/agency/users", "GET", "portal", 2),
        ("/api/v3/partner/rates", "GET", "partner-sync", 300),  # undocumented partner integration
        ("/internal/health", "GET", "lb-probe", 288),
    ]
    out = []
    for d in range(days):
        day0 = now - (days - d) * 86400
        for tmpl, method, client, vol in routes:
            n = int(vol / 10) + (1 if rnd.random() < (vol / 10) % 1 else 0)  # 10% sample to keep the file small
            for _ in range(n):
                path = tmpl.replace("{h}", rnd.choice(["H101", "H201", "H301", "H401"])).replace("{b}", f"WB{rnd.randint(1000, 9999)}")
                q = "?city=" + rnd.choice(["Goa", "Dubai", "Bali"]) if "search" in tmpl else ("?hotel_id=H201" if "partner" in tmpl else "")
                out.append({"ts": round(day0 + rnd.random() * 86400), "method": method, "path": path + q,
                            "status": 200, "client": client, "sampled": 0.1})
    # retired mobile app v1 still called by a few old installs until ~104 days ago
    for k in range(25):
        out.append({"ts": round(now - (104 + k * 0.6) * 86400), "method": "GET", "path": f"/api/v1/bookings/WB{rnd.randint(1000, 9999)}",
                    "status": 200, "client": "android-2.4", "sampled": 0.1})
    out.sort(key=lambda e: e["ts"])
    return out


def main():
    st = State()
    st.reset()
    st.deploy("v3.0", mutants=set())  # recordings come from correct behaviour
    serve(st, 8199)
    inputs = ROOT / "inputs"
    inputs.mkdir(exist_ok=True)
    har = record_har("http://127.0.0.1:8199")
    (inputs / "har.json").write_text(json.dumps({"note": "Synthetic recorded journeys (Waypoint B2B sandbox)", "sessions": har}, indent=1))
    logs = access_logs()
    with open(inputs / "access_log.jsonl", "w") as f:
        for e in logs:
            f.write(json.dumps(e) + "\n")
    print(f"wrote {sum(len(s['entries']) for s in har)} HAR entries in {len(har)} journeys, {len(logs)} log lines")


if __name__ == "__main__":
    main()
