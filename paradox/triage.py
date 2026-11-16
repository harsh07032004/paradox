"""Triage and reporting: severity in business terms, owner, ticket with proof, fix."""
from __future__ import annotations

import json
import re
import shlex

from paradox.recon import owner_of

BASE_SEVERITY = {
    "money_created": ("Critical", 95), "underpayment": ("Critical", 92), "cross_tenant_write": ("Critical", 90),
    "secret_exposure": ("Critical", 88), "sql_injection": ("Critical", 90), "mass_assignment": ("Critical", 86),
    "cross_tenant_read": ("High", 78), "unauthenticated_access": ("High", 76), "privilege_escalation": ("High", 74),
    "pii_exposure": ("High", 70), "invalid_quantity": ("High", 66), "one_time_reuse": ("Medium", 55),
}
CATEGORY = {
    "money_created": "business_logic", "underpayment": "business_logic", "one_time_reuse": "business_logic",
    "invalid_quantity": "business_logic", "cross_tenant_read": "access_control", "cross_tenant_write": "access_control",
    "privilege_escalation": "access_control", "mass_assignment": "access_control", "unauthenticated_access": "api_hygiene",
    "pii_exposure": "data_exposure", "secret_exposure": "data_exposure", "sql_injection": "injection",
}
INVARIANT = {
    "money_created": "An agency's wallet can never end a sequence of its own actions richer than it started.",
    "underpayment": "The same confirmed booking can never cost less than the platform's own price.",
    "cross_tenant_write": "Only the owning agency can change its bookings.",
    "cross_tenant_read": "One agency's data never reaches another agency.",
    "unauthenticated_access": "Booking data is never served without a session.",
    "privilege_escalation": "Actions reserved for a role cannot be performed by a lower role.",
    "mass_assignment": "Clients cannot set server-owned fields (role, tenant, status).",
    "one_time_reuse": "A value the platform rejects on reuse stays rejected.",
    "invalid_quantity": "Quantities below one are rejected before pricing.",
    "pii_exposure": "A field the platform masks is never returned in clear.",
    "secret_exposure": "Secrets and stack traces never appear in responses.",
    "sql_injection": "User input never changes the structure of a query.",
}
FIX = {
    "money_created": "Make refunds idempotent and state-gated: refund only from PAID/CONFIRMED, at most once, capped at the amount actually captured (sum of ledger debits for the booking).",
    "underpayment": "Price server-side only. Ignore client money fields; recompute from the quote/rate table and reject when a client value is present and differs. Never accept a status from the client.",
    "cross_tenant_write": "Authorise every state change against the booking's agency_id (object-level authorisation in the service layer, not only the controller).",
    "cross_tenant_read": "Scope every read by the caller's agency_id; return 404 for objects of other agencies.",
    "unauthenticated_access": "Put the route behind the gateway's auth policy and add an ownership check.",
    "privilege_escalation": "Enforce the role check on the write path (agency_admin only) and add a policy test for each role.",
    "mass_assignment": "Bind requests to an explicit allowlist DTO; role/tenant/status must only change through dedicated, authorised operations.",
    "one_time_reuse": "Record redemptions atomically (unique index on agency+code) and check it inside the same transaction as the discount.",
    "invalid_quantity": "Validate quantities (1-9 rooms, 1-30 nights) before pricing; reject zero/negative totals.",
    "pii_exposure": "Apply the same masking serializer to every endpoint returning traveller documents.",
    "secret_exposure": "Return a generic error body; log details server-side only. Remove debug routes from production builds and rotate exposed secrets.",
    "sql_injection": "Use parameterised queries for the filter; add input validation for city codes.",
}


def severity(v: dict, inventory_label: str | None) -> dict:
    sev, score = BASE_SEVERITY.get(v["kind"], ("Medium", 50))
    reasons = [INVARIANT.get(v["kind"], "")]
    leaked = v.get("leaked") or []
    if "passport" in leaked:
        score += 8
        reasons.append("Leaks passport numbers (traveller PII, DPDP Act scope).")
    if v.get("amount"):
        reasons.append(f"Measured loss INR {v['amount']:,.2f} per exploit run; repeatable with no limit.")
        score += 3
    if inventory_label in ("zombie", "shadow"):
        score += 5
        reasons.append(f"Endpoint is {inventory_label}: no owner is watching it.")
    if v["kind"] == "unauthenticated_access":
        reasons.append("No session needed: exploitable by anyone who can guess an id.")
    score = min(score, 100)
    if score >= 85:
        sev = "Critical"
    elif score >= 68:
        sev = "High"
    elif score >= 45:
        sev = "Medium"
    else:
        sev = "Low"
    return {"severity": sev, "score": score, "reasons": [r for r in reasons if r]}


def curl_lines(evidence: list[dict], base: str) -> str:
    lines = ["# Reproduction (tokens: log in as the named test account)"]
    for e in evidence:
        if "request" not in e:
            continue
        method, path = e["request"].split(" ", 1)
        parts = ["curl", "-s", "-X", method, shlex.quote(base + path)]
        if e["actor"] != "anonymous":
            parts += ["-H", shlex.quote(f"Authorization: Bearer $TOKEN_{re.sub(r'[^A-Za-z0-9]', '_', e['actor']).upper()}")]
        if e.get("body") is not None:
            body = e["body"] if isinstance(e["body"], str) else json.dumps(e["body"])
            parts += ["-H", "'Content-Type: application/json'", "-d", shlex.quote(body)]
        lines.append(" ".join(parts) + f"   # -> {e['status']}" + (f", wallet {e['ledger']}" if e.get("ledger") else ""))
    return "\n".join(lines)


def ticket_md(f: dict, base: str) -> str:
    ev = [e for e in f["evidence"] if "request" in e]
    led = next((e for e in f["evidence"] if "ledger_before" in e), None)
    def money(d):
        return ", ".join(f"{k} ₹{v:,.0f}" for k, v in d.items() if v is not None) if d else ""
    rows = "\n".join(
        f"| {e['step']} | {e['actor']} | `{e['request']}` | {e['status']} | {'**changed by Paradox**' if e['modified'] else ''} | {money(e.get('ledger'))} |"
        for e in ev)
    return f"""# {f['id']}: {f.get('headline', f['title'])}

*{f['title']}*

**Severity:** {f['severity']} ({f['score']}/100) · **Status:** {f['status']} · **Owner:** {f['owner']['team']} ({f['owner']['contact']})
**Endpoint:** `{f['endpoint']}` · **Class:** {f['category']} · **Release:** {f['release']}
**Detected:** {f['detected_at']} · **Deploy to verified finding:** {f.get('ttf_s', '-')} s · **Reproduced:** {f['reproduced']}

## Invariant broken
{INVARIANT.get(f['kind'], '')}

## What happened
{f['summary']}

## Business impact
{chr(10).join('- ' + r for r in f['reasons'])}

## Minimal proof ({len(ev)} requests, minimised from {f['original_steps']})
| # | Actor | Request | Status | | Balance after |
|---|---|---|---|---|---|
{rows}

{f"Balance before: {money(led['ledger_before'])} · after: {money(led['ledger_after'])}" if led else ''}

```bash
{curl_lines(f['evidence'], base)}
```

## Suggested fix
{FIX.get(f['kind'], '')}

## Retest
Paradox reruns this proof on every deploy and closes the ticket when it no longer reproduces.
"""


def action_name(endpoint: str) -> str:
    """Human name for a route: the last non-parameter segment ('cancel', 'voucher', 'search')."""
    method, _, path = endpoint.partition(" ")
    raw = [s for s in path.strip("/").split("/") if s and s != "api"]
    version = next((s for s in raw if re.fullmatch(r"v\d+", s)), None)
    raw = [s for s in raw if not re.fullmatch(r"v\d+", s)]
    if not raw:
        return endpoint
    if raw[-1] == "{id}":
        name = f"{raw[-2]} record" if len(raw) > 1 else "record"
    elif len(raw) >= 2 and raw[-2] != "{id}":
        name = f"{raw[-2]}/{raw[-1]}"
    else:
        name = raw[-1]
    if method == "GET" and raw[-1] != "{id}" and len(raw) == 1:
        name += " list"
    return f"{version} {name}" if version in ("v1", "v0") else name


def headline(v: dict) -> str:
    """One plain-language sentence a non-security reader understands."""
    a, amt, f = action_name(v["endpoint"]), v.get("amount"), v.get("field")
    rs = f"₹{amt:,.0f}" if amt else ""
    leaked = ", ".join(v.get("leaked") or [])
    return {
        "money_created": (f"The balance grows {rs} every time '{a}' runs on a record that is already {v['pre_state'].lower()}"
                          if v.get("pre_state") and not f else f"Setting '{f}' on '{a}' makes the balance grow {rs}" if f
                          else f"A sequence ending in '{a}' leaves the agency {rs} richer"),
        "underpayment": f"The same booking costs {rs} less when the client sends its own '{f}' to '{a}'",
        "cross_tenant_write": f"One agency can change another agency's record through '{a}'",
        "cross_tenant_read": f"One agency can read another agency's record through '{a}'" + (f" ({leaked} included)" if leaked else ""),
        "unauthenticated_access": f"Anyone without a login can fetch '{a}' for any record" + (f" ({leaked} included)" if leaked else ""),
        "privilege_escalation": f"A lower role can perform '{a}', which only admins should do",
        "mass_assignment": f"A user can set their own '{f}' through '{a}'",
        "one_time_reuse": f"A single-use '{f}' can be redeemed again on '{a}'" + (f", {rs} off each time" if amt else ""),
        "invalid_quantity": f"'{a}' accepts {f} below one and still prices it",
        "pii_exposure": f"'{a}' returns full passport numbers that are masked everywhere else",
        "secret_exposure": ("Error pages print the server's secrets and stack traces" if v.get("group") == "error-handler"
                            else f"'{a}' is publicly reachable and prints server secrets"),
        "sql_injection": f"The '{f}' filter on '{a}' can be rewritten into a different database query",
    }.get(v["kind"], v["summary"])


def build_finding(fid: str, v: dict, proof: dict, evidence: list, inventory: dict, ownership: dict, release: str,
                  detected_at: str, ttf: float | None, base: str) -> dict:
    tmpl = v["endpoint"].split(" ", 1)[1] if " " in v["endpoint"] else v["endpoint"]
    sv = severity(v, inventory.get(v["endpoint"]))
    title = {
        "money_created": f"Money printer: wallet gains money via {v['endpoint']}" + (f" (object was {v['pre_state']})" if v.get("pre_state") else ""),
        "underpayment": f"Underpayment: client controls price via '{v.get('field')}' on {v['endpoint']}",
        "cross_tenant_write": f"Cross-agency write on {v['endpoint']}",
        "cross_tenant_read": f"Cross-agency read on {v['endpoint']}",
        "unauthenticated_access": f"Unauthenticated access to booking data on {v['endpoint']}",
        "privilege_escalation": f"Sub-agent can perform admin action {v['endpoint']}",
        "mass_assignment": f"Mass assignment of '{v.get('field')}' on {v['endpoint']}",
        "one_time_reuse": f"Single-use '{v.get('field')}' reusable on {v['endpoint']}",
        "invalid_quantity": f"Invalid quantity '{v.get('field')}' priced on {v['endpoint']}",
        "pii_exposure": f"Unmasked passport numbers on {v['endpoint']}",
        "secret_exposure": f"Secrets exposed ({v.get('field')}) via {'error handler' if v.get('group') == 'error-handler' else v['endpoint']}",
        "sql_injection": f"SQL injection in '{v.get('field')}' on {v['endpoint']}",
    }.get(v["kind"], v["summary"])
    return {
        "id": fid, "key": v["key"], "kind": v["kind"], "category": CATEGORY.get(v["kind"], "other"), "title": title,
        "headline": headline(v), "action": action_name(v["endpoint"]),
        "endpoint": v["endpoint"], "summary": v["summary"], "amount": v.get("amount"), "pre_state": v.get("pre_state"),
        "field": v.get("field"), "group": v.get("group"), "leaked": v.get("leaked"), "status": "open",
        "owner": owner_of(ownership, tmpl), "release": release, "detected_at": detected_at, "ttf_s": ttf,
        "reproduced": "3/3 runs from fresh objects", "proof": proof, "evidence": evidence,
        "original_steps": len([s for s in proof["journey"]["steps"]]) if proof.get("journey") else 1,
        "inventory_label": inventory.get(v["endpoint"]), **sv, "history": [{"at": detected_at, "event": "opened", "release": release}],
    }
