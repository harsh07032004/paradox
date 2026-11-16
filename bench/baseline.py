"""Signature-based DAST baseline (our implementation of the generic rules most scanners apply).

It gets the same advantages as Paradox (bundle + HAR + a test account) but judges responses
by status codes and error/PII signatures, not by business invariants.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx

from paradox.recon import parse_bundle, template_of

PASSPORT = re.compile(r"\b[A-Z]\d{7}\b")
ERROR_SIG = re.compile(r"Traceback|Exception|SQL|sqlite|syntax error", re.I)


def run_baseline(base: str, inputs: Path) -> list[dict]:
    c = httpx.Client(base_url=base, timeout=10)
    har = json.loads((inputs / "har.json").read_text())
    acct = next(a for a in json.loads((inputs / "accounts.json").read_text())["accounts"] if a["username"] == "goa.sub")
    tok = c.post("/api/v3/auth/login", json={"username": acct["username"], "password": acct["password"]}).json()["token"]
    H = {"Authorization": f"Bearer {tok}"}
    findings: dict = {}

    def flag(kind, method, path, why):
        k = (kind, f"{method} {template_of(path)}")
        findings.setdefault(k, {"kind": kind, "endpoint": k[1], "summary": why})

    # spider: replay the first recorded journey to obtain live object ids (as a logged-in crawler would)
    live_ids, reqs = [], []
    ids_map = {}
    for e in har["sessions"][0]["entries"][1:]:
        path = e["path"]
        for old, new in ids_map.items():
            path = path.replace(old, new)
        body = e.get("request_body")
        if isinstance(body, dict):
            sb = json.dumps(body)
            for old, new in ids_map.items():
                sb = sb.replace(old, new)
            body = json.loads(sb)
        r = c.request(e["method"], path + ("?" + e["query"] if e["query"] else ""), json=body, headers=H)
        reqs.append((e["method"], path, e["query"], body))
        if isinstance(e["response_body"], dict) and r.headers.get("content-type", "").startswith("application/json"):
            for k, v in e["response_body"].items():
                if k.endswith("_id") and isinstance(v, str) and isinstance(r.json(), dict) and r.json().get(k):
                    ids_map[v] = r.json()[k]
                    live_ids.append(r.json()[k])
    js = c.get("/").text
    src = re.findall(r'src="([^"]+)"', js)
    routes = parse_bundle(c.get(src[0]).text) if src else []
    candidates = {(m, t) for m, t, _, _ in routes} | {(m, template_of(p)) for m, p, _, _ in reqs}

    for method, tmpl in sorted(candidates):
        if method != "GET":
            continue
        sample = next((p for m, p, _, _ in reqs if m == method and template_of(p) == tmpl), None)
        if sample is None:
            sample = tmpl.replace("{id}", live_ids[-1] if live_ids else "1")
        q = next((qq for m, p, qq, _ in reqs if p == sample), "")
        url = sample + ("?" + q if q else "")
        # rule 1: missing authentication
        r = c.get(url)
        if r.status_code == 200:
            flag("unauthenticated_access", "GET", sample, "200 without Authorization header")
        r = c.get(url, headers=H)
        # rule 2: sensitive data in response
        if PASSPORT.search(r.text):
            flag("pii_exposure", "GET", sample, "Passport-like pattern in response")
        # rule 3: IDOR by id increment
        m = re.search(r"([A-Z]+)(\d+)", sample.split("/")[-1] if "{id}" in tmpl else "")
        if "{id}" in tmpl:
            for seg in sample.split("/"):
                mm = re.fullmatch(r"([A-Z]+)(\d+)", seg)
                if mm:
                    for delta in (-1, 1, -2):
                        alt = sample.replace(seg, f"{mm.group(1)}{int(mm.group(2)) + delta}")
                        if c.get(alt, headers=H).status_code == 200:
                            flag("cross_tenant_read", "GET", sample, f"Neighbouring id {alt} returned 200")
                            break
        # rule 4: error-based SQL injection on query params
        for k, v in parse_qsl(q):
            rr = c.get(sample + "?" + urlencode({k: v + "'"}), headers=H)
            if rr.status_code >= 500 or ERROR_SIG.search(rr.text):
                flag("sql_injection", "GET", sample, f"Error after quote in '{k}'")
    # rule 5: verbose errors on malformed bodies
    for method, path, _, body in reqs:
        if method in ("POST", "PUT", "PATCH") and isinstance(body, dict):
            rr = c.request(method, path, content="{\"x\": ", headers={**H, "Content-Type": "application/json"})
            if ERROR_SIG.search(rr.text) and "Traceback" in rr.text:
                k = ("secret_exposure", "*error*")
                findings.setdefault(k, {"kind": "secret_exposure", "endpoint": f"{method} {template_of(path)}", "group": "error-handler",
                                        "summary": "Stack trace in error response"})
    # rule 6: common debug paths
    for p in ("/internal/debug/vars", "/debug", "/actuator/env", "/.env"):
        rr = c.get(p)
        if rr.status_code == 200 and re.search(r"SECRET|KEY|PASSWORD", rr.text, re.I):
            flag("secret_exposure", "GET", p, "Debug endpoint exposes configuration")
    return list(findings.values())
