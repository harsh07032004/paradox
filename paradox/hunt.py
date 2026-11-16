"""Hunting: mutate learned journeys, then check business invariants that must hold for ANY
correct B2B travel platform. A finding exists only when an invariant breaks.

Invariants (oracles)
  money_created          a tenant's balance must never end a sequence richer than it started
  underpayment           the same final booking must never cost less than the untouched journey
  cross_tenant_read      a tenant's canary data must never reach another tenant
  cross_tenant_write     another tenant must never change a tenant's object
  unauthenticated_access object data must never reach a caller without a session
  privilege_escalation   an action seen only from a higher role must not succeed from a lower one
  mass_assignment        a client must not set server-owned fields (role, tenant, status)
  one_time_reuse         a value the platform rejects on reuse must stay rejected
  invalid_quantity       quantities must not go to zero/negative and still price
  pii_exposure           a field served masked must never be served in clear
  secret_exposure        secrets / stack traces must never appear in a response
  sql_injection          boolean conditions in input must not change result sets

Mutation operators: repeat a step, skip a step, graft an action from another journey,
tamper a money field, mass-assign a server field, negate a quantity, swap tenant,
drop the session, downgrade role, inject boolean SQL, malform the body.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re

from paradox.recon import MONEY, QTY, SECRET_PATTERNS, ID_SEG, walk
from paradox.runner import RunResult, Runner, Semantics, graft, is_ref, synth_step

EPS = 0.5


def ekey(st: dict) -> str:
    return f"{st['method']} {st['template']}"


class Hunter:
    def __init__(self, sem: Semantics, runner: Runner, bus=None):
        self.sem, self.runner, self.bus = sem, runner, bus
        self.model = sem.model
        self.review: list[dict] = []
        self.suppressed = 0
        self.experiments_run = 0

    def emit(self, kind, msg, **kw):
        if self.bus:
            self.bus.emit(kind, msg, **kw)

    # ================================================================ ledger discovery
    def calibrate_ledger(self) -> dict | None:
        """Find the money balance by experiment: the numeric field that moves when money moves."""
        cands = []
        for j in self.sem.journeys:
            for st in j["steps"]:
                if st["method"] == "GET" and "{id}" not in st["template"] and isinstance(st["har_response"], dict):
                    for k, v in st["har_response"].items():
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            cands.append((ekey(st), k))
        cands = sorted(set(cands))
        settle_j = next((j for j in self.sem.journeys if any(t.settle and t.settle in {ekey(s) for s in j["steps"]} for t in self.sem.types.values())), None)
        if not cands or not settle_j:
            return None
        user = settle_j["user"]
        hdr = self.runner.auth(user)

        def snap():
            out = {}
            for ep, f in cands:
                r = self.runner.gate.request("GET", self.runner.base + ep.split(" ", 1)[1], headers=hdr, actor=user)
                try:
                    out[(ep, f)] = float(r.json()[f])
                except Exception:
                    pass
            return out

        before = snap()
        res = self.runner.run(settle_j)
        after = snap()
        moved = {k: after[k] - before[k] for k in before if k in after and abs(after[k] - before[k]) > EPS}
        # the ledger is the field that moved by exactly an amount the platform itself reported in a money-named field
        charged = {round(abs(v), 2) for s in res.steps if isinstance(s.json, dict) for p, v in walk(s.json)
                   if isinstance(v, (int, float)) and not isinstance(v, bool) and p and MONEY.search(str(p[-1])) and abs(v) > 1}
        # a journey may move money several times (ticket + seat): accept a sum of reported amounts
        from itertools import combinations
        vals = sorted(charged)[:14]
        sums = {round(sum(c), 2) for n in range(1, min(4, len(vals)) + 1) for c in combinations(vals, n)}
        pick = next(((ep, f) for (ep, f), d in moved.items() if round(abs(d), 2) in sums), None)
        self.runner.cleanup(res)
        if pick:
            self.sem.balance = {"endpoint": pick[0], "field": pick[1]}
            self.emit("learn", f"Ledger located by experiment: {pick[0]} -> '{pick[1]}' moved by the amount charged")
        return self.sem.balance

    # ================================================================ planning
    def journeys(self, extra_endpoints: list) -> list[dict]:
        """HAR journeys + grafted actions + synthesised steps for endpoints with no recorded traffic."""
        js = list(self.sem.journeys)
        action_steps: dict[str, dict] = {}
        for j in self.sem.journeys:
            for st in j["steps"]:
                if st["method"] != "GET" and any(is_ref(s) for s in st["path"]) and not st["body"]:
                    action_steps.setdefault(ekey(st), st)
        for t in self.sem.types.values():
            for j in self.sem.journeys:
                c = self.sem.creator_step(j, t)
                if c is None:
                    continue
                present = {ekey(s) for s in j["steps"][c:]}
                for key, st in action_steps.items():
                    if key in t.consumers and key not in present:
                        step = synth_step(st["method"], st["template"], c, t.id_path, [], {})
                        step["synthetic"] = False
                        js.append(graft(j, step, key.split("/")[-1]))
        # endpoints known only from bundle / probing
        for ep in extra_endpoints:
            t = self.sem.type_of_template(ep.template)
            if t is None:
                if "{id}" not in ep.template and ep.method == "GET":
                    js.append({"id": f"P:{ep.template}", "name": f"probe {ep.template}", "user": self.sem.journeys[0]["user"], "origin": "synth",
                               "steps": [{"method": "GET", "template": ep.template, "auth": False, "har_status": 200, "path": ep.template.strip("/").split("/"),
                                          "query": [], "body": None, "har_response": None, "synthetic": True}]})
                continue
            hosts = [j for j in self.sem.journeys if self.sem.creator_step(j, t) is not None]
            if ep.method != "GET" and t.settle:
                hosts = [j for j in hosts if t.settle in {ekey(s) for s in j["steps"]}] or hosts
            for j in hosts[:2]:
                c = self.sem.creator_step(j, t)
                st = synth_step(ep.method, ep.template, c, t.id_path, sorted(ep.body_keys), j["steps"][c]["har_response"])
                js.append(graft(j, st, ep.template.split("/")[-1] + ("@" + ep.template.split("/")[2] if ep.method == "GET" else "")))
        return js

    def plan(self, extra_endpoints: list, focus: set | None = None) -> list[dict]:
        exps, seen = [], set()
        roles = {u: a for u, a in self.sem.vault.items() if not a.get("requires_approval")}
        top_role = max(roles.values(), key=lambda a: a["privilege"])["role"]

        def add(op, j, i, plan, field=None, value=None, ctx="", control=False):
            st = j["steps"][i] if i is not None else None
            key = (op, ekey(st) if st else j["id"], field, json.dumps(value, default=str), ctx)
            if key in seen:
                return
            seen.add(key)
            exps.append({"id": f"E{len(exps)+1:04d}", "op": op, "journey": j, "target": i, "plan": plan, "field": field, "value": value,
                         "endpoint": ekey(st) if st else j["id"], "control": control})

        for j in self.journeys(extra_endpoints):
            actor = j["user"]
            a_tenant = self.sem.vault[actor]["tenant"]
            others = [u for u in roles if roles[u]["tenant"] != a_tenant and roles[u]["role"] == roles[actor]["role"]] or \
                     [u for u in roles if roles[u]["tenant"] != a_tenant]
            lower = [u for u in roles if roles[u]["tenant"] == a_tenant and roles[u]["privilege"] < roles[actor]["privilege"]]
            if j["origin"] != "har":
                add("plain", j, None, {"trace": True}, ctx=j["id"])
            for i, st in enumerate(j["steps"]):
                k = ekey(st)
                ctx = json.dumps([(ekey(s), sorted(x for x, v in (s["body"] or {}).items() if v not in (None, "") and not is_ref(v)))
                                  for s in j["steps"][:i] if s["method"] != "GET"])
                consumes = any(is_ref(s) for s in st["path"])
                har_resp = st["har_response"] if isinstance(st["har_response"], dict) else {}
                body = st["body"] if isinstance(st["body"], dict) else {}
                if st["method"] != "GET":
                    add("repeat", j, i, {"repeat": {i: 2}, "trace": True}, ctx=ctx)
                    if i < len(j["steps"]) - 1:
                        add("skip", j, i, {"skip": [i], "trace": True}, ctx=ctx)
                    money = {f for f in body if MONEY.search(f)} | {f for f in har_resp if MONEY.search(f) and f not in body} | set(st.get("money_keys", []))
                    # an action on an object may also accept the object's own price fields (e.g. fare on a ticket call)
                    for seg in st["path"]:
                        if is_ref(seg):
                            src = j["steps"][seg["$ref"][0]]["har_response"]
                            if isinstance(src, dict):
                                money |= {f for f, v in src.items() if MONEY.search(f) and isinstance(v, (int, float)) and not isinstance(v, bool)}
                    for f in sorted(money):
                        add("tamper", j, i, {"set": {i: {f: 1}}, "trace": True}, f, 1, control=True)
                    for f in sorted(har_resp):
                        if f in body or ID_SEG.match(str(har_resp[f]) or "") and f.endswith("id") and not re.search(r"agency|tenant|org|account", f):
                            continue
                        vals = []
                        if f == self.model.status_field:
                            vals = [v for v in self.model.status_values if v != har_resp[f]]
                        elif re.search(r"role", f):
                            vals = [top_role] if har_resp[f] != top_role else []
                        elif re.search(r"agency|tenant|org", f):
                            vals = [roles[others[0]]["tenant"]] if others else []
                        for v in vals:
                            add("mass_assign", j, i, {"set": {i: {f: v}}, "trace": True}, f, v, control=True)
                    for f, v in body.items():
                        if isinstance(v, int) and not isinstance(v, bool) and not MONEY.search(f) and (QTY.match(f) or True):
                            for nv in (-1, 0):
                                add("quantity", j, i, {"set": {i: {f: nv}}, "trace": True}, f, nv)
                    for (ek, f, val) in self.model.one_time_fields:
                        if ek == k and body.get(f) == val:
                            add("one_time", j, i, {"repeat": {i: 2}}, f, body.get(f), ctx=j["id"])
                    if body:
                        add("error_probe", j, i, {"raw": {i: "{\"" + next(iter(body)) + "\": "}}, "malformed", None)
                        nums = {f: "x" for f, v in body.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
                        if nums:
                            add("error_probe", j, i, {"set": {i: nums}}, "type", None)
                if consumes or st.get("synthetic"):
                    for o in others[:1]:
                        add("cross_tenant", j, i, {"as": {i: o}}, o, None)
                    add("unauth", j, i, {"as": {i: None}})
                ep = self.model.endpoints.get(k)
                if ep and ep.roles_seen and lower and all(self.sem.vault[actor]["role"] == r for r in ep.roles_seen):
                    add("vertical", j, i, {"as": {i: lower[0]}}, lower[0], None)
                if st["method"] == "GET":
                    for qi, (qk, qv) in enumerate(st["query"]):
                        if isinstance(qv, str) and not is_ref(qv):
                            add("sqli", j, i, {}, qk, qv)
        if focus:
            exps.sort(key=lambda e: 0 if (e["endpoint"] in focus or any(ekey(s) in focus for s in e["journey"]["steps"])) else 1)
        return exps

    # ================================================================ execution
    def execute(self, exp: dict) -> list[dict]:
        self.experiments_run += 1
        self.runner.gate.context = exp["id"]
        j, op = exp["journey"], exp["op"]
        if op == "sqli":
            return self._sqli(exp)
        ctrl = self.runner.run(j, {"trace": False}) if exp["control"] else None
        ctrl_outcome = self._outcome(ctrl) if ctrl else None
        if ctrl:
            self.runner.cleanup(ctrl)
        prior = self._restore_point(exp)
        res = self.runner.run(j, {**exp["plan"], "trace": True})
        out = self._evaluate(exp, res, ctrl, ctrl_outcome)
        self.runner.cleanup(res)
        self._restore(exp, prior)
        return out

    def _restore_point(self, exp):
        if exp["op"] == "mass_assign" and exp["field"] and re.search(r"role", exp["field"]):
            st = exp["journey"]["steps"][exp["target"]]
            r = st["har_response"] if isinstance(st["har_response"], dict) else {}
            return r.get(exp["field"])
        return None

    def _restore(self, exp, prior):
        if prior is None:
            return
        st = exp["journey"]["steps"][exp["target"]]
        user = exp["plan"].get("actor") or exp["journey"]["user"]
        self.runner.gate.request(st["method"], self.runner.base + st["template"], headers=self.runner.auth(user), json_body={exp["field"]: prior}, actor=user)

    def _outcome(self, res: RunResult) -> str | None:
        if not res or not res.created:
            return None
        sig = []
        canaries = set(res.canaries)
        for tname, oid, tenant in res.created:
            t = self.sem.types[tname]
            obj = self.runner.read(t, oid, self.sem.accounts(tenant)[0]) or {}
            sig.append(sorted((k, v) for k, v in obj.items() if isinstance(v, (str, int, float)) and not MONEY.search(k)
                              and v not in canaries and not (isinstance(v, str) and ID_SEG.match(v))))
        return json.dumps(sig, default=str)

    # ================================================================ oracles
    def _evaluate(self, exp, res: RunResult, ctrl, ctrl_outcome) -> list[dict]:
        v: list[dict] = []
        j, op, i = exp["journey"], exp["op"], exp["target"]
        actor = exp["plan"].get("actor") or j["user"]
        a_tenant = self.sem.vault[actor]["tenant"]
        tgt = res.ok(i) if i is not None else None
        tgt_any = next((s for s in res.steps if s.idx == i and s.status), None) if i is not None else None

        def V(kind, endpoint, summary, **kw):
            v.append({"kind": kind, "endpoint": endpoint, "summary": summary, "exp": exp["id"], **kw})

        # ---- money invariants (the shadow ledger)
        if self.sem.balance:
            d = res.delta(a_tenant)
            if d > EPS:
                culprit, pre = self._culprit(exp, res, a_tenant)
                V("money_created", culprit, f"Wallet of {a_tenant} ended INR {d:,.2f} richer after the sequence",
                  amount=d, pre_state=pre, field=exp["field"] if op in ("tamper", "quantity", "mass_assign") else None)
            elif ctrl is not None and ctrl_outcome is not None:
                out = self._outcome(res)
                gap = round(d - ctrl.delta(a_tenant), 2)
                if out == ctrl_outcome and gap > EPS:
                    V("underpayment", exp["endpoint"], f"Identical booking outcome cost INR {gap:,.2f} less after setting '{exp['field']}'",
                      amount=gap, field=exp["field"], pre_state=None)
        # ---- tenant isolation
        if op == "cross_tenant" and tgt:
            owner_canaries = {c for c, (t, _) in res.canaries.items() if t == a_tenant}
            leaked = sorted(c for c in owner_canaries if c in tgt.text)
            kinds = sorted({res.canaries[c][1] for c in leaked})
            if tgt.method == "GET":
                if leaked or (a_tenant in tgt.text and any(oid in tgt.text for _, oid, t in res.created if t == a_tenant)):
                    V("cross_tenant_read", exp["endpoint"], f"{exp['field']} ({self.sem.vault[exp['field']]['tenant']}) read {a_tenant}'s object" +
                      (f"; leaked {', '.join(kinds)}" if kinds else ""), leaked=kinds, field=None)
            else:
                changed = self._object_changed(res, i, a_tenant)
                if changed or abs(res.delta(a_tenant)) > EPS:
                    V("cross_tenant_write", exp["endpoint"], f"{exp['field']} changed {a_tenant}'s object ({changed or 'balance moved'})", field=None)
        if op == "unauth" and tgt:
            owner_canaries = [c for c in res.canaries if c in tgt.text]
            if owner_canaries or any(oid in tgt.text for _, oid, _t in res.created):
                V("unauthenticated_access", exp["endpoint"], "Object data served to a caller with no session" +
                  (f"; leaked {', '.join(sorted({res.canaries[c][1] for c in owner_canaries}))}" if owner_canaries else ""), field=None)
        # ---- vertical privilege
        if op == "vertical" and tgt:
            if tgt.method == "GET":
                self._add_review(exp, f"{exp['field']} ({self.sem.vault[exp['field']]['role']}) can read an endpoint only "
                                      f"{self.sem.vault[actor]['role']} used in recorded traffic. Policy question, not auto-filed.")
            else:
                before, after = self._get_around(res, i, tgt)
                if before is not None and after is not None and before != after:
                    V("privilege_escalation", exp["endpoint"], f"{self.sem.vault[exp['field']]['role']} performed an action only "
                      f"{self.sem.vault[actor]['role']} performs; state changed {before} -> {after}", field=None)
        # ---- mass assignment of server-owned privilege/tenant fields
        if op == "mass_assign" and tgt and isinstance(tgt.json, dict) and exp["field"] != self.model.status_field:
            if tgt.json.get(exp["field"]) == exp["value"]:
                V("mass_assignment", exp["endpoint"], f"Client set server-owned field '{exp['field']}' to {exp['value']!r}", field=exp["field"])
        # ---- one-time values
        if op == "one_time":
            oks = [s for s in res.steps if s.idx == i and s.status and 200 <= s.status < 300]
            same = [s for s in res.steps if s.status and 200 <= s.status < 300 and isinstance(s.request_body, dict)
                    and s.request_body.get(exp["field"]) == exp["value"] and f"{s.method}" == j["steps"][i]["method"]]
            if len(oks) >= 2 or len(same) >= 2:
                disc = next((float(vv) for s in same[1:] if isinstance(s.json, dict) for kk, vv in s.json.items()
                             if re.search("discount", kk) and isinstance(vv, (int, float))), 0.0)
                V("one_time_reuse", exp["endpoint"], f"Value of '{exp['field']}' the platform rejects on reuse was accepted again", amount=disc, field=exp["field"])
        # ---- quantities
        if op == "quantity" and tgt and isinstance(tgt.json, dict) and not any(x["kind"] == "money_created" for x in v):
            neg = [kk for kk, vv in tgt.json.items() if MONEY.search(kk) and isinstance(vv, (int, float)) and vv <= 0 and not re.search("discount|refund", kk)]
            if neg:
                V("invalid_quantity", exp["endpoint"], f"'{exp['field']}'={exp['value']} accepted and priced at {tgt.json[neg[0]]}", field=exp["field"])
        # ---- passive: PII and secrets in every response
        canary_pp = {c for c, (t, kind) in res.canaries.items() if kind == "passport"}
        for s in res.steps:
            if not s.status:
                continue
            pii_field = next((f for f in self.model.masked_fields if re.search(r"passport|document|doc_no|id_no", f, re.I)), None)
            if 200 <= s.status < 300 and pii_field and s.actor and op not in ("cross_tenant", "unauth"):
                if any(c in s.text for c in canary_pp):
                    V("pii_exposure", f"{s.method} {self._tmpl(j, s.idx)}", f"Passport number served unmasked (platform masks '{pii_field}' elsewhere)",
                      field="passport", passive=True)
            for name, rx in SECRET_PATTERNS:
                if rx.search(s.text):
                    group = "error-handler" if s.status >= 500 else f"{s.method} {self._tmpl(j, s.idx)}"
                    V("secret_exposure", f"{s.method} {self._tmpl(j, s.idx)}", f"Response exposes {name} (HTTP {s.status})", field=name, group=group, passive=True)
                    break
        return v

    def _tmpl(self, j, idx):
        return j["steps"][idx]["template"]

    def _culprit(self, exp, res, tenant):
        """Which step execution moved money the wrong way, and the object's state just before it."""
        steps = [s for s in res.steps if s.status]
        occ = None
        if exp["op"] in ("tamper", "quantity", "mass_assign"):
            occ = next((n for n, s in enumerate(steps) if s.idx == exp["target"]), None)
        else:
            # the culprit is the step at which the running balance first rises above where the sequence started
            start = res.before.get(tenant, 0)
            for n, s in enumerate(steps):
                if s.balance_after and s.balance_after.get(tenant) is not None and s.balance_after[tenant] - start > EPS:
                    occ = n
                    break
        if occ is None:
            occ = next((n for n, s in enumerate(steps) if s.idx == exp["target"]), len(steps) - 1)
        pre = None
        for s in steps[:occ]:
            if isinstance(s.json, dict) and 200 <= s.status < 300 and self.model.status_field in s.json:
                pre = s.json[self.model.status_field]
        st = exp["journey"]["steps"][steps[occ].idx]
        return f"{st['method']} {st['template']}", pre

    def _object_changed(self, res, i, tenant):
        prev = None
        for s in res.steps:
            if s.idx >= i:
                break
            if isinstance(s.json, dict) and self.model.status_field in s.json and s.status and s.status < 300:
                prev = s.json[self.model.status_field]
        for tname, oid, t in res.created:
            if t != tenant:
                continue
            obj = self.runner.read(self.sem.types[tname], oid, self.sem.accounts(tenant)[0]) or {}
            now = obj.get(self.model.status_field)
            if prev and now and now != prev:
                return f"{self.model.status_field} {prev} -> {now}"
        return None

    def _get_around(self, res, i, tgt):
        """For a write by a lower role: compare the same-template GET before and after it."""
        tmpl = tgt.url.split("?")[0]
        before = next((s.json for s in reversed(res.steps) if s.idx < i and s.method == "GET" and s.url.split("?")[0] == tmpl and s.status == 200), None)
        after = next((s.json for s in res.steps if s.idx > i and s.method == "GET" and s.url.split("?")[0] == tmpl and s.status == 200), None)
        return before, after

    def _add_review(self, exp, text):
        if not any(r["endpoint"] == exp["endpoint"] for r in self.review):
            self.review.append({"endpoint": exp["endpoint"], "question": text, "exp": exp["id"]})
            self.emit("review", f"Needs a human: {exp['endpoint']}")

    def _sqli(self, exp) -> list[dict]:
        j, i, f, val = exp["journey"], exp["target"], exp["field"], exp["value"]
        single = {**j, "steps": [j["steps"][i]]}

        def size(q):
            r = self.runner.run(single, {"query": {0: {f: q}}})
            s = r.steps[0]
            if not isinstance(s.json, dict):
                return -1, s
            return max((len(x) for x in s.json.values() if isinstance(x, list)), default=0), s

        base, _ = size(val)
        t, ts = size(f"{val}' OR '1'='1")
        fl, _ = size(f"{val}' AND '1'='2")
        if base >= 1 and t > base and 0 <= fl < base:
            return [{"kind": "sql_injection", "endpoint": exp["endpoint"], "exp": exp["id"], "field": f,
                     "summary": f"Boolean injection in '{f}': TRUE condition returned {t} rows, FALSE {fl}, normal {base}",
                     "evidence_url": ts.url}]
        return []

    # ================================================================ verification
    @staticmethod
    def vkey(v: dict) -> str:
        if v["kind"] == "secret_exposure":
            return f"secret_exposure|{v.get('group')}"
        parts = [v["kind"], v["endpoint"], v.get("pre_state") or "", v.get("field") or ""]
        return "|".join(str(p) for p in parts)

    def verify(self, exp: dict, v: dict, runs: int = 2) -> dict | None:
        key = self.vkey(v)
        for _ in range(runs):
            if not any(self.vkey(x) == key for x in self.execute(exp)):
                self.suppressed += 1
                self.emit("noise", f"Dropped unreproducible signal: {v['summary']}")
                return None
        proof = self.minimise(exp, key)
        return proof

    def minimise(self, exp: dict, key: str) -> dict:
        """Delta-debug the journey: skip each step that is not needed to reproduce the violation."""
        e = copy.deepcopy(exp)
        if e["op"] == "sqli":
            return e
        protect = {e["target"]} if e["target"] is not None else set()
        for idx in range(len(e["journey"]["steps"]) - 1, -1, -1):
            if idx in protect or idx in set(e["plan"].get("skip", [])):
                continue
            trial = copy.deepcopy(e)
            trial["plan"]["skip"] = sorted(set(trial["plan"].get("skip", [])) | {idx})
            if any(self.vkey(x) == key for x in self.execute(trial)):
                e = trial
        return e

    def evidence(self, exp: dict) -> list[dict]:
        """Run the minimal proof once more with a full ledger trace; return a readable transcript."""
        if exp["op"] == "sqli":
            return []
        self.runner.gate.context = exp["id"] + "-proof"
        plan = {**exp["plan"], "trace": True}
        res = self.runner.run(exp["journey"], plan)
        out = []
        for s in res.steps:
            if s.skipped:
                continue
            out.append({"step": s.idx, "actor": s.actor or "anonymous", "request": f"{s.method} {s.url.replace(self.runner.base, '')}",
                        "body": s.request_body, "status": s.status, "response": s.text[:500],
                        "ledger": s.balance_after, "modified": s.modified})
        out.append({"ledger_before": res.before, "ledger_after": res.after})
        self.runner.cleanup(res)
        return out
