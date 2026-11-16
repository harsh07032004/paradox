"""Recon: learn the application without documentation.

Sources (as listed in the problem statement):
  * the front-end JavaScript bundle (routes + request body shapes)
  * recorded traffic (HAR) from normal journeys, per role
  * API-gateway access logs (30-90 day window)
  * bounded probing for hidden/old routes (versions, internal/debug/test prefixes)

Output: an `AppModel` (endpoint map + learned semantics) and an inventory labelled
active / zombie / shadow / retired with a recommendation per endpoint.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ID_SEG = re.compile(r"^(?!v\d+$)(?:(?=.*\d)[A-Za-z0-9_-]{3,}|[A-Z0-9]{5,}|[0-9a-fA-F-]{32,36})$")
MONEY = re.compile(r"(amount|amt|total|price|fare|gross|net|charged|debit|credit|refund|balance|available|cost|paid|discount|tax|fee|due)", re.I)
QTY = re.compile(r"^(rooms|nights|qty|quantity|pax|count|units|seats|guests|adults|children|bags|items)$", re.I)
SECRET_PATTERNS = [
    ("signing secret", re.compile(r"SECRET_KEY\W{1,4}[\w-]{6,}")),
    ("payment key", re.compile(r"\b(sk|rk)_(test|live)_[A-Za-z0-9]{6,}")),
    ("db credentials", re.compile(r"\b\w+://[^\s:/@]+:[^\s@/]+@[\w.-]+")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("stack trace", re.compile(r"Traceback \(most recent call last\)|at [\w.$]+\([\w]+\.java:\d+\)")),
]
PROBE_PREFIXES = ["/internal", "/debug", "/admin", "/test", "/beta", "/old", "/actuator", "/api/internal", "/api/debug"]
PROBE_SUFFIXES = ["", "/health", "/status", "/info", "/vars", "/env", "/config", "/metrics", "/debug/vars", "/debug/config", "/debug/env"]


def template_of(path: str) -> str:
    segs = path.split("?")[0].strip("/").split("/")
    return "/" + "/".join("{id}" if ID_SEG.match(s) else s for s in segs if s != "")


def strip_version(tmpl: str) -> str:
    return re.sub(r"/v\d+/", "/v*/", tmpl)


@dataclass
class Endpoint:
    method: str
    template: str
    sources: set = field(default_factory=set)
    body_keys: set = field(default_factory=set)
    query_keys: set = field(default_factory=set)
    response_keys: set = field(default_factory=set)
    roles_seen: set = field(default_factory=set)
    auth_seen: set = field(default_factory=set)
    probe_status: int | None = None
    probe_unauth_status: int | None = None
    probe_sample: str = ""
    hits_window: int = 0
    last_seen: float | None = None
    clients: set = field(default_factory=set)

    @property
    def key(self) -> str:
        return f"{self.method} {self.template}"

    def to_json(self) -> dict:
        d = {k: (sorted(v) if isinstance(v, set) else v) for k, v in self.__dict__.items()}
        d["key"] = self.key
        return d


@dataclass
class AppModel:
    base: str
    endpoints: dict = field(default_factory=dict)  # key -> Endpoint
    sessions: list = field(default_factory=list)   # raw HAR sessions
    bundle_hash: str = ""
    bundle_sig: dict = field(default_factory=dict)  # key -> sorted body keys (for change detection)
    not_found_fp: tuple = (404, "")
    login: dict | None = None                    # {"template", "user_field", "pass_field", "token_field"}
    auth: dict = field(default_factory=lambda: {"header": "Authorization", "prefix": "Bearer "})
    one_time_fields: set = field(default_factory=set)   # {(endpoint key, field, value)}
    masked_fields: set = field(default_factory=set)     # field names served masked in normal responses
    status_values: list = field(default_factory=list)   # status enum in order first observed
    status_field: str | None = None

    def ep(self, method: str, template: str) -> Endpoint:
        k = f"{method} {template}"
        if k not in self.endpoints:
            self.endpoints[k] = Endpoint(method, template)
        return self.endpoints[k]

    def find(self, method: str, path: str) -> Endpoint | None:
        return self.endpoints.get(f"{method} {template_of(path)}")


# --------------------------------------------------------------------------- bundle
JS_CALL = re.compile(r"""['"](GET|POST|PUT|PATCH|DELETE)['"]\s*,\s*[`'"](/[^`'"]+)[`'"]\s*(?:,\s*\{([^}]*)\})?""")


def parse_bundle(js: str) -> list[tuple[str, str, list[str], list[str]]]:
    out = []
    for method, url, body in JS_CALL.findall(js):
        url = re.sub(r"\$\{[^}]+\}", "X0000", url)
        path, _, q = url.partition("?")
        tmpl = template_of(path)
        qkeys = [k for k, _ in parse_qsl(q, keep_blank_values=True)]
        bkeys = re.findall(r"(\w+)\s*:", body or "")
        out.append((method, tmpl, bkeys, qkeys))
    return out


def fetch_bundle(gate, base: str) -> tuple[str, str]:
    html = gate.request("GET", base + "/").text
    srcs = re.findall(r"<script[^>]+src=\"([^\"]+)\"", html)
    js = "".join(gate.request("GET", base + s).text for s in srcs if s.startswith("/"))
    import hashlib
    return js, hashlib.sha1(js.encode()).hexdigest()[:12]


# --------------------------------------------------------------------------- HAR
def walk(obj, path=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, path + (i,))
    else:
        yield path, obj


def learn_from_har(model: AppModel, har: dict, vault: dict) -> None:
    model.sessions = har["sessions"]
    enum_vals: dict = {}
    for sess in model.sessions:
        user, token = None, None
        values_seen: dict = {}
        for e in sess["entries"]:
            resp = e["response_body"] if isinstance(e["response_body"], dict) else {}
            body = e.get("request_body") or {}
            ep = model.ep(e["method"], template_of(e["path"]))
            ep.sources.add("har")
            ep.auth_seen.add(e["auth"])
            ep.body_keys.update(body.keys() if isinstance(body, dict) else [])
            ep.query_keys.update(k for k, _ in parse_qsl(e.get("query", "")))
            ep.response_keys.update(resp.keys())
            # session scheme: the header that carries the issued token, and its prefix
            if token:
                for hk, hv in (e.get("request_headers") or {}).items():
                    if isinstance(hv, str) and token in hv:
                        model.auth = {"header": hk, "prefix": hv.replace(token, "")}
            # login endpoint: issues a token in exchange for the vault credential fields
            tok_field = next((k for k in resp if re.search(r"token|jwt|session|access", k, re.I)
                              and isinstance(resp[k], str) and len(resp[k]) >= 16), None)
            if tok_field and isinstance(body, dict):
                uf = next((k for k in body if re.search(r"user|login|email", k, re.I)), None)
                pf = next((k for k in body if re.search(r"pass|secret|pwd", k, re.I)), None)
                if uf and pf:
                    model.login = {"template": ep.template, "user_field": uf, "pass_field": pf, "token_field": tok_field}
                    user, token = body[uf], resp[tok_field]
            if user and user in vault:
                ep.roles_seen.add(vault[user]["role"])
            # one-time values: accepted once, then rejected, and the rejection names the field
            if isinstance(body, dict):
                for k, v in body.items():
                    if isinstance(v, str) and v:
                        prev = values_seen.get((ep.key, k, v))
                        if prev is not None and prev < 300 and 400 <= e["status"] < 500 and k.lower() in json.dumps(resp).lower():
                            model.one_time_fields.add((ep.key, k, v))
                        values_seen.setdefault((ep.key, k, v), e["status"])
            # masking policy and lifecycle-state enums
            for p, v in walk(resp):
                if isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9]{0,4}\*{3,}[A-Za-z0-9]{0,4}", v):
                    model.masked_fields.add(str(p[-1]))
                if p and isinstance(p[-1], str) and isinstance(v, str) and re.fullmatch(r"[A-Z][A-Z_]{2,}", v):
                    lst = enum_vals.setdefault(p[-1], [])
                    if v not in lst:
                        lst.append(v)
    # the lifecycle field: an enum with several values, preferring names like status/state
    cands = {k: v for k, v in enum_vals.items() if len(v) >= 2}
    if cands:
        model.status_field = max(cands, key=lambda k: (bool(re.search(r"status|state|stage", k, re.I)), len(cands[k])))
        model.status_values = cands[model.status_field]


# --------------------------------------------------------------------------- logs
def learn_from_logs(model: AppModel, log_path: Path, window_days: int = 90) -> dict:
    now = time.time()
    cutoff = now - window_days * 86400
    seen: dict = {}
    with open(log_path) as f:
        for line in f:
            e = json.loads(line)
            tmpl = template_of(urlsplit(e["path"]).path)
            k = f"{e['method']} {tmpl}"
            s = seen.setdefault(k, {"hits": 0, "last": 0, "clients": set(), "method": e["method"], "template": tmpl})
            if e["ts"] >= cutoff:
                s["hits"] += int(round(1 / e.get("sampled", 1)))
            s["last"] = max(s["last"], e["ts"])
            s["clients"].add(e.get("client", "?"))
    for k, s in seen.items():
        ep = model.ep(s["method"], s["template"])
        ep.sources.add("traffic")
        ep.hits_window, ep.last_seen, ep.clients = s["hits"], s["last"], s["clients"]
    return seen


# --------------------------------------------------------------------------- probing
def fingerprint(r) -> tuple:
    try:
        keys = tuple(sorted(r.json().keys())) if isinstance(r.json(), dict) else ("list",)
    except Exception:
        keys = ("text",)
    return (r.status_code, keys)


def probe(model: AppModel, gate, sample_ids: dict, auth_headers: dict | None) -> list[str]:
    """Bounded discovery of undocumented routes. Returns keys of endpoints that respond."""
    base = model.base
    nf = fingerprint(gate.request("GET", f"{base}/{uuid.uuid4().hex[:10]}/{uuid.uuid4().hex[:6]}", headers=auth_headers))
    model.not_found_fp = nf
    candidates: set[str] = set()
    for ep in list(model.endpoints.values()):
        m = re.search(r"/v(\d+)/", ep.template)
        if m and ep.method == "GET":
            n = int(m.group(1))
            for v in range(1, n + 2):
                if v != n:
                    candidates.add(ep.template.replace(f"/v{n}/", f"/v{v}/", 1))
    for p in PROBE_PREFIXES:
        for s in PROBE_SUFFIXES:
            candidates.add(p + s)
    found = []
    for tmpl in sorted(candidates):
        if f"GET {tmpl}" in model.endpoints and model.endpoints[f"GET {tmpl}"].probe_status:
            continue
        sid = sample_ids.get(strip_version(tmpl))
        if "{id}" in tmpl and not sid:
            continue
        url = base + tmpl.replace("{id}", sid or "")
        r = gate.request("GET", url, headers=auth_headers)
        if fingerprint(r) == nf or r.status_code == 405:
            continue
        ep = model.ep("GET", tmpl)
        ep.sources.add("probe")
        ep.probe_status = r.status_code
        ep.probe_sample = r.text[:400]
        ep.response_keys.update(r.json().keys() if r.headers.get("content-type", "").startswith("application/json") and isinstance(r.json(), dict) else [])
        u = gate.request("GET", url)
        ep.probe_unauth_status = u.status_code
        found.append(ep.key)
    return found


# --------------------------------------------------------------------------- inventory
def classify(model: AppModel, ownership: dict, window_days: int = 90, new_keys: set | None = None) -> list[dict]:
    now = time.time()
    rows = []
    for ep in sorted(model.endpoints.values(), key=lambda e: e.template):
        mapped = bool(ep.sources & {"bundle", "har"})
        traffic = ep.hits_window > 0
        responds = ep.probe_status is not None and ep.probe_status not in (404, 405)
        if ep.probe_status == 410:
            label, rec = "retired", "Correctly decommissioned (410 Gone). Remove route from gateway config when convenient."
        elif mapped and traffic:
            label, rec = "active", "Keep. Covered by continuous testing."
        elif mapped and not traffic:
            label = "new" if new_keys and ep.key in new_keys else "dormant"
            rec = "Shipped in latest deploy, prioritised for testing." if label == "new" else "Mapped in the UI but unused for the window; confirm it is still needed."
        elif traffic and not mapped:
            label, rec = "shadow", "In use but undocumented. Add to the API catalogue, assign an owner, put behind the gateway's auth policy."
        elif responds and not traffic:
            label = "zombie"
            rec = "No legitimate traffic in the window but still live. Decommission (return 410) or restrict to an allowlist."
        else:
            label, rec = "unknown", "Insufficient evidence."
        secrets = [n for n, rx in SECRET_PATTERNS if rx.search(ep.probe_sample or "")]
        rows.append({
            "endpoint": ep.key, "label": label, "sources": sorted(ep.sources), "hits_90d": ep.hits_window,
            "last_seen_days": round((now - ep.last_seen) / 86400, 1) if ep.last_seen else None,
            "auth_required": (ep.probe_unauth_status in (401, 403)) if ep.probe_unauth_status else (True in ep.auth_seen and False not in ep.auth_seen) or None,
            "clients": sorted(ep.clients), "exposes": secrets or [k for k in sorted(ep.response_keys) if re.search(r"passport|email|gstin|phone|card", k)][:5],
            "owner": owner_of(ownership, ep.template), "recommendation": rec,
        })
    return rows


def owner_of(ownership: dict, template: str) -> dict:
    best = ("", {"team": "platform-security", "contact": "appsec@waypoint.example"})
    for prefix, owner in ownership.items():
        if template.startswith(prefix) and len(prefix) > len(best[0]):
            best = (prefix, owner)
    return best[1]


def openapi(model: AppModel, inventory: list[dict]) -> dict:
    labels = {r["endpoint"]: r["label"] for r in inventory}
    paths: dict = {}
    for ep in model.endpoints.values():
        if labels.get(ep.key) in ("unknown",):
            continue
        op = {"summary": f"Inferred by Paradox ({', '.join(sorted(ep.sources))})", "x-paradox-label": labels.get(ep.key),
              "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}] if "{id}" in ep.template else []}
        op["parameters"] += [{"name": q, "in": "query", "schema": {"type": "string"}} for q in sorted(ep.query_keys)]
        if ep.body_keys:
            op["requestBody"] = {"content": {"application/json": {"schema": {"type": "object", "properties": {k: {} for k in sorted(ep.body_keys)}}}}}
        if True in ep.auth_seen:
            op["security"] = [{"bearer": []}]
        op["responses"] = {"200": {"description": "OK", "content": {"application/json": {"schema": {"type": "object", "properties": {k: {} for k in sorted(ep.response_keys)}}}}}}
        paths.setdefault(ep.template, {})[ep.method.lower()] = op
    return {"openapi": "3.0.3", "info": {"title": "Inferred API (generated by Paradox, no spec provided)", "version": time.strftime("%Y-%m-%d")},
            "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}}, "paths": dict(sorted(paths.items()))}
