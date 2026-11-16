"""SkyLane Air B2B: a HOLDOUT target written after the agent was frozen, with deliberately
different conventions, to test that Paradox generalises instead of fitting Waypoint.

Differences from Waypoint: flights not hotels; `X-Session` header not Bearer; session issued
for {login, secret}; lifecycle field `state` (ON_HOLD/TICKETED/VOIDED); object ids are PNR
codes; money is a credit line (`available`); passports masked as `NX****67`; orgs not agencies;
roles agent/supervisor; a v1 route left over from an old app; promo codes.

Planted defects (switch with SKY_BUGS, default all):
  S1 void twice credits twice           S2 ticket trusts client 'fare'
  S3 PNR read skips org check           S4 negative ancillary count credits money
  S5 e-ticket served without session    S6 single-use promo reusable
  S7 /v1/pnrs/{pnr} legacy route, no org check, unmasked passports
"""
from __future__ import annotations

import json
import random
import secrets
import string
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

FLIGHTS = {
    ("DEL", "BOM"): [("FK-AI865", "AI", 5400.0), ("FK-6E211", "6E", 4890.0)],
    ("BLR", "GOI"): [("FK-6E509", "6E", 3720.0)],
    ("DEL", "DXB"): [("FK-EK511", "EK", 18450.0)],
}
SEAT_PRICE = 450.0
PROMOS = {"FIRSTFLY": 0.08}


class Sky:
    def __init__(self, bugs: set[str]):
        self.bugs = bugs
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.users = {
            "ag.north": dict(secret="Sky#North1", org="ORG-NORTH", role="agent"),
            "sup.north": dict(secret="Sky#North2", org="ORG-NORTH", role="supervisor"),
            "ag.south": dict(secret="Sky#South1", org="ORG-SOUTH", role="agent"),
            "sup.south": dict(secret="Sky#South2", org="ORG-SOUTH", role="supervisor"),
        }
        self.credit = {"ORG-NORTH": 300000.0, "ORG-SOUTH": 300000.0}
        self.sessions, self.pnrs, self.promo_used = {}, {}, set()
        self.limits = {"ORG-NORTH": 20000.0, "ORG-SOUTH": 20000.0}


def mask(p: str) -> str:
    return p[:2] + "*" * (len(p) - 4) + p[-2:]


def pnr_code(rnd=random.SystemRandom()) -> str:
    return "".join(rnd.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(6))  # letters only, like many real PNRs


def create(sky: Sky) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    B = lambda b: b in sky.bugs  # noqa: E731

    def who(req: Request):
        return sky.sessions.get(req.headers.get("x-session", ""))

    def no(status, msg):
        return JSONResponse({"message": msg, "code": status}, status_code=status)

    def view(p, clear=False):
        return {"pnr": p["pnr"], "state": p["state"], "org": p["org"], "flight_key": p["flight_key"], "fare": p["fare"],
                "contact": {"email": p["email"]}, "passengers": [{"full_name": x["full_name"], "passport_no": x["passport_no"] if clear else mask(x["passport_no"])} for x in p["pax"]],
                "ancillaries": p["anc"]}

    @app.get("/", response_class=HTMLResponse)
    def home():
        return '<html><body>SkyLane agent desk<script src="/assets/desk.js"></script></body></html>'

    @app.get("/assets/desk.js")
    def js():
        return Response("""const call=(m,u,b)=>fetch(u,{method:m,headers:{'X-Session':localStorage.s,'Content-Type':'application/json'},body:b&&JSON.stringify(b)});
const desk={login:(l,s)=>call('POST','/v2/session',{login:l,secret:s}),flights:(f,t,d)=>call('GET',`/v2/flights?from=${f}&to=${t}&date=${d}`),
hold:(k,p,e,c)=>call('POST','/v2/pnrs',{flight_key:k,passengers:p,contact:e,promo:c}),ticket:(p)=>call('POST',`/v2/pnrs/${p}/ticket`),
void:(p)=>call('POST',`/v2/pnrs/${p}/void`),pnr:(p)=>call('GET',`/v2/pnrs/${p}`),eticket:(p)=>call('GET',`/v2/pnrs/${p}/eticket`),
seats:(p,n)=>call('POST',`/v2/pnrs/${p}/ancillaries`,{item:'SEAT',count:n}),credit:()=>call('GET','/v2/credit'),
limit:(v)=>call('PUT','/v2/org/limits',{per_ticket_limit:v}),limits:()=>call('GET','/v2/org/limits')};""", media_type="application/javascript")

    @app.post("/v2/session")
    async def session(req: Request):
        b = await req.json()
        u = sky.users.get(b.get("login"))
        if not u or u["secret"] != b.get("secret"):
            return no(401, "bad login")
        tok = secrets.token_hex(16)
        sky.sessions[tok] = dict(login=b["login"], **u)
        return {"session": tok, "org": u["org"], "role": u["role"]}

    @app.get("/v2/flights")
    def flights(req: Request, date: str = ""):
        q = dict(req.query_params)
        rows = FLIGHTS.get((q.get("from", ""), q.get("to", "")), [])
        return {"flights": [{"flight_key": k, "carrier": c, "fare": f, "date": date} for k, c, f in rows]}

    @app.post("/v2/pnrs")
    async def hold(req: Request):
        u = who(req)
        if not u:
            return no(401, "session required")
        b = await req.json()
        fl = next((f for rows in FLIGHTS.values() for f in rows if f[0] == b.get("flight_key")), None)
        pax = b.get("passengers") or []
        if not fl or not pax:
            return no(422, "flight_key and passengers required")
        fare = fl[2] * len(pax)
        code = b.get("promo")
        if code:
            if code not in PROMOS:
                return no(422, "unknown promo")
            if (u["org"], code) in sky.promo_used and not B("S6"):
                return no(422, f"promo {code} already redeemed by your org")
            sky.promo_used.add((u["org"], code))
            fare = round(fare * (1 - PROMOS[code]), 2)
        p = dict(pnr=pnr_code(), state="ON_HOLD", org=u["org"], flight_key=fl[0], fare=fare, email=str((b.get("contact") or {}).get("email", "")),
                 pax=[{"full_name": str(x.get("full_name")), "passport_no": str(x.get("passport_no"))} for x in pax], anc=[], debited=0.0)
        sky.pnrs[p["pnr"]] = p
        return view(p)

    def mine(req, pnr, skip=False):
        u = who(req)
        if not u:
            return None, None, no(401, "session required")
        p = sky.pnrs.get(pnr)
        if not p or (p["org"] != u["org"] and not skip):
            return None, None, no(404, "no such pnr")
        return u, p, None

    @app.get("/v2/pnrs/{pnr}")
    def read(req: Request, pnr: str):
        u, p, e = mine(req, pnr, skip=B("S3"))
        return e or view(p)

    @app.post("/v2/pnrs/{pnr}/ticket")
    async def ticket(req: Request, pnr: str):
        u, p, e = mine(req, pnr)
        if e:
            return e
        raw = await req.body()
        b = json.loads(raw) if raw else {}
        with sky.lock:
            if p["state"] != "ON_HOLD":
                return no(409, "not on hold")
            fare = float(b["fare"]) if B("S2") and "fare" in b else p["fare"]
            if sky.credit[p["org"]] < fare:
                return no(402, "credit exhausted")
            sky.credit[p["org"]] -= fare
            p["debited"], p["state"] = fare, "TICKETED"
        return {"pnr": pnr, "state": "TICKETED", "debited": fare}

    @app.post("/v2/pnrs/{pnr}/void")
    def void(req: Request, pnr: str):
        u, p, e = mine(req, pnr)
        if e:
            return e
        with sky.lock:
            if p["state"] == "VOIDED" and not B("S1"):
                return no(409, "already voided")
            if p["state"] == "ON_HOLD":
                p["state"] = "VOIDED"
                return {"pnr": pnr, "state": "VOIDED", "credited": 0.0}
            back = p["debited"] + sum(a["price"] for a in p["anc"])
            sky.credit[p["org"]] += back
            p["state"] = "VOIDED"
        return {"pnr": pnr, "state": "VOIDED", "credited": back}

    @app.post("/v2/pnrs/{pnr}/ancillaries")
    async def anc(req: Request, pnr: str):
        u, p, e = mine(req, pnr)
        if e:
            return e
        b = await req.json()
        n = int(b.get("count", 1))
        if not (n <= 4 if B("S4") else 1 <= n <= 4):
            return no(422, "count 1-4")
        if p["state"] != "TICKETED":
            return no(409, "ticket first")
        price = SEAT_PRICE * n
        sky.credit[p["org"]] -= price
        p["anc"].append({"item": b.get("item", "SEAT"), "count": n, "price": price})
        return {"pnr": pnr, "item": b.get("item", "SEAT"), "count": n, "price": price}

    @app.get("/v2/pnrs/{pnr}/eticket")
    def eticket(req: Request, pnr: str):
        if B("S5"):
            p = sky.pnrs.get(pnr)
            if not p:
                return no(404, "no such pnr")
        else:
            u, p, e = mine(req, pnr)
            if e:
                return e
        return {"eticket": "098-" + p["pnr"], "pnr": p["pnr"], "lead_passenger": p["pax"][0]["full_name"], "contact": p["email"], "state": p["state"]}

    @app.get("/v2/credit")
    def credit(req: Request):
        u = who(req)
        if not u:
            return no(401, "session required")
        return {"org": u["org"], "available": round(sky.credit[u["org"]], 2), "currency": "INR"}

    @app.get("/v2/org/limits")
    def limits(req: Request):
        u = who(req)
        if not u:
            return no(401, "session required")
        return {"org": u["org"], "per_ticket_limit": sky.limits[u["org"]]}

    @app.put("/v2/org/limits")
    async def set_limits(req: Request):
        u = who(req)
        if not u:
            return no(401, "session required")
        if u["role"] != "supervisor":
            return no(403, "supervisor only")
        b = await req.json()
        sky.limits[u["org"]] = float(b.get("per_ticket_limit", sky.limits[u["org"]]))
        return {"org": u["org"], "per_ticket_limit": sky.limits[u["org"]]}

    @app.get("/v1/pnrs/{pnr}")
    def legacy(req: Request, pnr: str):
        if not B("S7"):
            return no(404, "no such pnr")
        if not who(req):
            return no(401, "session required")
        p = sky.pnrs.get(pnr)
        return view(p, clear=True) if p else no(404, "no such pnr")

    return app


GROUND_TRUTH = {
    "S1": {"endpoint": "POST /v2/pnrs/{id}/void", "kinds": {"money_created"}, "pre_state": "VOIDED"},
    "S2": {"endpoint": "POST /v2/pnrs/{id}/ticket", "kinds": {"underpayment", "money_created"}, "field": "fare"},
    "S3": {"endpoint": "GET /v2/pnrs/{id}", "kinds": {"cross_tenant_read"}},
    "S4": {"endpoint": "POST /v2/pnrs/{id}/ancillaries", "kinds": {"money_created", "invalid_quantity"}, "field": "count"},
    "S5": {"endpoint": "GET /v2/pnrs/{id}/eticket", "kinds": {"unauthenticated_access", "cross_tenant_read"}},
    "S6": {"endpoint": "POST /v2/pnrs", "kinds": {"one_time_reuse"}},
    "S7": {"endpoint": "GET /v1/pnrs/{id}", "kinds": {"cross_tenant_read", "pii_exposure"}},
}
