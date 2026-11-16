"""Holdout evaluation: record SkyLane traffic from a clean instance, then point the UNCHANGED
Paradox agent at a buggy instance and at a clean one, and score against ground truth.

    python -m holdout.run_holdout
"""
from __future__ import annotations

import json
import random
import shutil
import threading
import time
from pathlib import Path

import httpx
import uvicorn

from holdout.skylane import GROUND_TRUTH, Sky, create
from paradox.engine import Bus, Engine
from target.mutants import matches as _unused  # noqa: F401  (same matching rules, local copy below)

ROOT = Path(__file__).resolve().parent
INP = ROOT / "inputs"
PORT = 8300


def serve(sky: Sky, port: int):
    srv = uvicorn.Server(uvicorn.Config(create(sky), host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.02)
    return srv


def record(base: str) -> list[dict]:
    c = httpx.Client(base_url=base, timeout=5)
    sessions = []

    def journey(name, login, secret):
        s = {"journey": name, "entries": []}
        sessions.append(s)
        tok = {}

        def call(m, u, b=None):
            h = {"X-Session": tok["t"]} if tok else {}
            r = c.request(m, u, json=b, headers=h)
            path, _, q = u.partition("?")
            s["entries"].append({"method": m, "path": path, "query": q, "auth": bool(tok), "request_headers": h,
                                 "request_body": b, "status": r.status_code, "response_body": r.json()})
            return r.json()
        tok["t"] = call("POST", "/v2/session", {"login": login, "secret": secret})["session"]
        return call

    call = journey("hold-ticket-seat", "ag.north", "Sky#North1")
    f = call("GET", "/v2/flights?from=DEL&to=BOM&date=2026-12-20")
    p = call("POST", "/v2/pnrs", {"flight_key": f["flights"][0]["flight_key"], "passengers": [{"full_name": "Kavya Menon", "passport_no": "NX4417263"}],
                                  "contact": {"email": "desk@northtravels.example"}, "promo": None})
    call("POST", f"/v2/pnrs/{p['pnr']}/ticket")
    call("POST", f"/v2/pnrs/{p['pnr']}/ancillaries", {"item": "SEAT", "count": 1})
    call("GET", f"/v2/pnrs/{p['pnr']}")
    call("GET", f"/v2/pnrs/{p['pnr']}/eticket")
    call("GET", "/v2/credit")

    call = journey("ticket-then-void", "ag.south", "Sky#South1")
    f = call("GET", "/v2/flights?from=BLR&to=GOI&date=2026-12-22")
    p = call("POST", "/v2/pnrs", {"flight_key": f["flights"][0]["flight_key"], "passengers": [{"full_name": "Rohan Pillai", "passport_no": "PS9902114"}],
                                  "contact": {"email": "ops@southtrips.example"}, "promo": None})
    call("POST", f"/v2/pnrs/{p['pnr']}/ticket")
    call("POST", f"/v2/pnrs/{p['pnr']}/void")
    call("GET", f"/v2/pnrs/{p['pnr']}")
    call("GET", "/v2/credit")

    call = journey("promo", "ag.north", "Sky#North1")
    call("POST", "/v2/pnrs", {"flight_key": "FK-EK511", "passengers": [{"full_name": "Nisha Rao", "passport_no": "NX5512980"}],
                              "contact": {"email": "desk@northtravels.example"}, "promo": "FIRSTFLY"})
    call("POST", "/v2/pnrs", {"flight_key": "FK-EK511", "passengers": [{"full_name": "Nisha Rao", "passport_no": "NX5512980"}],
                              "contact": {"email": "desk@northtravels.example"}, "promo": "FIRSTFLY"})

    call = journey("supervisor-limits", "sup.south", "Sky#South2")
    call("GET", "/v2/org/limits")
    call("PUT", "/v2/org/limits", {"per_ticket_limit": 25000})
    call("GET", "/v2/org/limits")
    call("PUT", "/v2/org/limits", {"per_ticket_limit": 20000})
    return sessions


def write_inputs(base: str):
    INP.mkdir(exist_ok=True)
    (INP / "har.json").write_text(json.dumps({"sessions": record(base)}, indent=1))
    rnd, now, lines = random.Random(3), time.time(), []
    for d in range(95):
        for path, m, n in [("/v2/flights", "GET", 30), ("/v2/pnrs", "POST", 8), ("/v2/pnrs/ABCDEF/ticket", "POST", 7), ("/v2/pnrs/ABCDEF", "GET", 12),
                           ("/v2/pnrs/ABCDEF/eticket", "GET", 5), ("/v2/credit", "GET", 9), ("/v2/pnrs/ABCDEF/void", "POST", 1),
                           ("/v2/pnrs/ABCDEF/ancillaries", "POST", 2), ("/v2/org/limits", "GET", 1)]:
            for _ in range(n):
                lines.append({"ts": now - (95 - d) * 86400 + rnd.random() * 86400, "method": m, "path": path.replace("ABCDEF", "".join(rnd.choices("ABCDEFGHJKLMNPQRSTUVWXYZ", k=6))),
                              "status": 200, "client": "desk", "sampled": 1})
    with open(INP / "access_log.jsonl", "w") as f:
        for e in sorted(lines, key=lambda e: e["ts"]):
            f.write(json.dumps(e) + "\n")
    (INP / "scope.json").write_text(json.dumps({"allowed_origins": [f"http://127.0.0.1:{PORT}"], "max_rps": 400, "max_requests_per_cycle": 20000, "traffic_window_days": 90}))
    (INP / "accounts.json").write_text(json.dumps({"accounts": [
        {"username": "ag.north", "password": "Sky#North1", "tenant": "ORG-NORTH", "role": "agent", "privilege": 1},
        {"username": "sup.north", "password": "Sky#North2", "tenant": "ORG-NORTH", "role": "supervisor", "privilege": 2},
        {"username": "ag.south", "password": "Sky#South1", "tenant": "ORG-SOUTH", "role": "agent", "privilege": 1},
        {"username": "sup.south", "password": "Sky#South2", "tenant": "ORG-SOUTH", "role": "supervisor", "privilege": 2}]}))
    (INP / "ownership.json").write_text(json.dumps({"/v2/pnrs": {"team": "air-booking", "contact": "air@skylane.example"},
                                                    "/v1": {"team": "legacy-app", "contact": "air@skylane.example"}}))


def matches(gt: dict, f: dict) -> bool:
    if f["kind"] not in gt["kinds"] or f["endpoint"] != gt["endpoint"]:
        return False
    return all(f.get(k) == gt[k] for k in ("pre_state", "field") if k in gt)


def evaluate(bugs: set[str], label: str) -> dict:
    sky = Sky(bugs)
    srv = serve(sky, PORT)
    out = ROOT / "runs" / label
    shutil.rmtree(out, ignore_errors=True)
    eng = Engine(INP, out, Bus(echo=False))
    eng.release = label
    t0 = time.time()
    eng.cycle("holdout", release=label)
    secs = round(time.time() - t0, 1)
    fs = eng.snapshot()["findings"]
    det = {b: any(matches(GROUND_TRUTH[b], f) for f in fs) for b in sorted(bugs)}
    tp = [f for f in fs if any(matches(GROUND_TRUTH[b], f) for b in bugs)]
    srv.should_exit = True
    time.sleep(0.5)
    return {"label": label, "seconds": secs, "requests": eng.gate.sent, "detected": det,
            "recall": sum(det.values()) / len(det) if det else 1.0, "findings": [f"{f['kind']} @ {f['endpoint']} [{f.get('pre_state') or f.get('field') or ''}]" for f in fs],
            "false_positives": [f"{f['kind']} @ {f['endpoint']}" for f in fs if f not in tp],
            "learned": {"auth": eng.model.auth, "login": eng.model.login, "status_field": eng.model.status_field,
                        "status_values": eng.model.status_values, "ledger": eng.sem.balance, "masked": sorted(eng.model.masked_fields),
                        "object_types": {t.name: {"observer": t.observer, "release": t.release, "settle": t.settle} for t in eng.sem.types.values()},
                        "one_time": sorted(map(list, eng.model.one_time_fields)),
                        "inventory": {r["endpoint"]: r["label"] for r in eng.inventory}}}


def main():
    clean = Sky(set())
    srv = serve(clean, PORT)
    write_inputs(f"http://127.0.0.1:{PORT}")
    srv.should_exit = True
    time.sleep(0.5)
    results = [evaluate(set(GROUND_TRUTH), "all-bugs"), evaluate(set(), "clean")]
    (ROOT / "results.json").write_text(json.dumps(results, indent=1))
    for r in results:
        print(json.dumps({k: r[k] for k in ("label", "seconds", "requests", "recall", "detected", "false_positives")}))
    print(json.dumps(results[0]["learned"], indent=1))
    print("\n".join(results[0]["findings"]))


if __name__ == "__main__":
    main()
