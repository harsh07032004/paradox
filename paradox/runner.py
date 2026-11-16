"""Journey templates and replay.

A journey is a recorded user flow (search -> quote -> book -> pay ...) turned into a
template: every value that a later request takes from an earlier response (booking id,
quote id, hotel id, room code) becomes a data-flow reference, so the journey can be
replayed with fresh objects, by any test account, with any step changed.

Replay also:
  * plants unique canary values (email, traveller name, passport) in created objects,
    so a leak to another tenant or an anonymous caller is proven by the canary itself
  * snapshots each tenant's balance (the shadow ledger) before / after / per step
  * cleans up: releases every object it created that is still open
"""
from __future__ import annotations

import copy
import json
import random
import re
import string
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode

from paradox.recon import ID_SEG, MONEY, AppModel, strip_version, template_of, walk


def is_ref(x) -> bool:
    return isinstance(x, dict) and "$ref" in x


@dataclass
class ObjType:
    name: str
    creator: str                 # endpoint key that creates it
    id_path: tuple
    consumers: set = field(default_factory=set)
    observer: str | None = None  # GET endpoint key that reads it
    release: str | None = None   # action that closes it (e.g. cancel)
    settle: str | None = None    # action that moves money for it (e.g. pay)


class Semantics:
    """Business semantics learned from traffic: object types, observers, actions, ledger."""

    def __init__(self, model: AppModel, vault: dict):
        self.model = model
        self.vault = vault
        self.types: dict[str, ObjType] = {}
        self.journeys: list[dict] = []
        self.balance: dict | None = None  # {"endpoint", "field"}
        self.terminal_status = model.status_values[-1] if model.status_values else None
        self._learn()

    # ------------------------------------------------------------ learning
    def _learn(self) -> None:
        for n, sess in enumerate(self.model.sessions):
            entries = sess["entries"]
            login_i = next((i for i, e in enumerate(entries) if self.model.login and template_of(e["path"]) == self.model.login["template"]), None)
            user = entries[login_i]["request_body"][self.model.login["user_field"]] if login_i is not None else None
            raw = [e for i, e in enumerate(entries) if i != login_i]
            steps = []
            for i, e in enumerate(raw):
                st = {"method": e["method"], "template": template_of(e["path"]), "auth": e["auth"], "har_status": e["status"],
                      "path": [], "query": [], "body": None, "har_response": e["response_body"]}
                for seg in e["path"].strip("/").split("/"):
                    st["path"].append(self._bind(seg, raw[:i]) if ID_SEG.match(seg) else seg)
                st["query"] = [[k, self._bind(v, raw[:i])] for k, v in parse_qsl(e.get("query", ""))]
                st["body"] = self._bind_tree(e.get("request_body"), raw[:i])
                steps.append(st)
            self.journeys.append({"id": f"J{n+1}", "name": sess["journey"], "user": user, "steps": steps, "origin": "har"})
        # object types from producer -> consumer references
        for j in self.journeys:
            for st in j["steps"]:
                for seg in st["path"]:
                    if is_ref(seg):
                        k, p = seg["$ref"]
                        prod = j["steps"][k]
                        if prod["method"] == "POST":  # a value a POST returned and later steps address: an object id
                            name = f"{prod['method']} {prod['template']}#{'.'.join(map(str, p))}"
                            t = self.types.setdefault(name, ObjType(name, f"{prod['method']} {prod['template']}", tuple(p)))
                            t.consumers.add(f"{st['method']} {st['template']}")
                            resp = st["har_response"] if isinstance(st["har_response"], dict) else {}
                            status = resp.get(self.model.status_field) if self.model.status_field else None
                            if st["method"] == "GET" and st["template"].count("{id}") == 1 and status:
                                if not t.observer or len(st["template"]) < len(t.observer):
                                    t.observer = f"GET {st['template']}"
                            if st["method"] != "GET" and status:
                                if status == self.terminal_status:
                                    t.release = f"{st['method']} {st['template']}"
                                elif self.model.status_values and status != self.model.status_values[0]:
                                    t.settle = f"{st['method']} {st['template']}"

    def _bind(self, value, earlier: list):
        if not isinstance(value, str) or len(value) < 3:
            return value
        for k in range(len(earlier)):  # earliest producer = the step that created the value
            resp = earlier[k]["response_body"]
            for p, v in walk(resp):
                if v == value:
                    return {"$ref": [k, list(p)]}
        return value

    def _bind_tree(self, tree, earlier):
        if isinstance(tree, dict):
            return {k: self._bind_tree(v, earlier) for k, v in tree.items()}
        if isinstance(tree, list):
            return [self._bind_tree(v, earlier) for v in tree]
        return self._bind(tree, earlier)

    # ------------------------------------------------------------ helpers
    def type_of_template(self, tmpl: str) -> ObjType | None:
        """Which object type does an (unseen) endpoint with an {id} act on? Matched by collection path."""
        if "{id}" not in tmpl:
            return None
        head = strip_version(tmpl.split("{id}")[0])
        for t in self.types.values():
            for c in t.consumers:
                if strip_version(c.split(" ", 1)[1].split("{id}")[0]) == head:
                    return t
        return None

    def creator_step(self, journey: dict, t: ObjType) -> int | None:
        for i, st in enumerate(journey["steps"]):
            if f"{st['method']} {st['template']}" == t.creator and 200 <= st["har_status"] < 300:
                return i
        return None

    def accounts(self, tenant: str | None = None, role: str | None = None) -> list[str]:
        return [u for u, a in self.vault.items() if (tenant is None or a["tenant"] == tenant) and (role is None or a["role"] == role)
                and not a.get("requires_approval")]


# ---------------------------------------------------------------------- execution
@dataclass
class StepResult:
    idx: int
    method: str
    url: str
    actor: str | None
    status: int | None = None
    json: object = None
    text: str = ""
    skipped: str | None = None
    balance_after: dict | None = None
    request_body: object = None
    modified: bool = False


@dataclass
class RunResult:
    steps: list = field(default_factory=list)
    created: list = field(default_factory=list)  # (type name, id, tenant)
    canaries: dict = field(default_factory=dict)  # value -> (tenant, kind)
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)

    def delta(self, tenant: str) -> float:
        return round(self.after.get(tenant, 0) - self.before.get(tenant, 0), 2)

    def ok(self, idx: int) -> StepResult | None:
        return next((s for s in self.steps if s.idx == idx and s.status and 200 <= s.status < 300), None)


class Runner:
    def __init__(self, sem: Semantics, gate, base: str):
        self.sem, self.gate, self.base = sem, gate, base
        self.tokens: dict[str, str] = {}
        self.rnd = random.Random()

    # ------------------------------------------------------------ accounts & ledger
    def token(self, user: str | None) -> str | None:
        if user is None:
            return None
        if user not in self.tokens:
            lg = self.sem.model.login
            r = self.gate.request("POST", self.base + lg["template"], json_body={lg["user_field"]: user, lg["pass_field"]: self.sem.vault[user]["password"]}, actor=user)
            self.tokens[user] = r.json()[lg["token_field"]]
        return self.tokens[user]

    def auth(self, user: str | None) -> dict:
        """Session header in the scheme learned from traffic (header name + prefix)."""
        if not user:
            return {}
        a = self.sem.model.auth
        return {a["header"]: a["prefix"] + self.token(user)}

    def tenant(self, user: str | None) -> str | None:
        return self.sem.vault[user]["tenant"] if user else None

    def balance(self, tenant: str) -> float | None:
        if not self.sem.balance:
            return None
        user = self.sem.accounts(tenant)[0]
        r = self.gate.request("GET", self.base + self.sem.balance["endpoint"].split(" ", 1)[1], headers=self.auth(user), actor=user)
        try:
            return float(r.json()[self.sem.balance["field"]])
        except Exception:
            return None

    def read(self, obj_type: ObjType, oid: str, user: str) -> dict | None:
        if not obj_type.observer:
            return None
        r = self.gate.request("GET", self.base + obj_type.observer.split(" ", 1)[1].replace("{id}", oid), headers=self.auth(user), actor=user)
        return r.json() if r.status_code == 200 else None

    # ------------------------------------------------------------ canaries
    def _canary(self, value, tenant, reg):
        tag = "".join(self.rnd.choices(string.ascii_lowercase + string.digits, k=6))
        if not isinstance(value, str):
            return value
        if "@" in value:
            v = f"pdx.{tag}@canary.test"
            reg[v] = (tenant, "email")
        elif re.fullmatch(r"[A-Z]{1,2}\d{6,9}", value):
            lead = re.match(r"[A-Z]+", value).group(0)
            v = lead + "".join(self.rnd.choices(string.digits, k=len(value) - len(lead)))
            reg[v] = (tenant, "passport")
        elif re.fullmatch(r"[A-Za-z]+( [A-Za-z]+)+", value):
            v = f"Pdx {tag.capitalize()}"
            reg[v] = (tenant, "name")
        else:
            return value
        return v

    def _resolve(self, x, results: dict, tenant, reg, canary: bool):
        if is_ref(x):
            k, p = x["$ref"]
            r = results.get(k)
            if r is None or r.json is None:
                raise KeyError("unresolved")
            v = r.json
            for key in p:
                v = v[key]
            if "add" in x and isinstance(v, (int, float)):
                v = v + x["add"]
            return v
        if isinstance(x, dict):
            return {k: self._resolve(v, results, tenant, reg, canary) for k, v in x.items()}
        if isinstance(x, list):
            return [self._resolve(v, results, tenant, reg, canary) for v in x]
        return self._canary(x, tenant, reg) if canary else x

    # ------------------------------------------------------------ replay
    def run(self, journey: dict, plan: dict | None = None) -> RunResult:
        plan = plan or {}
        actor = plan.get("actor") or journey["user"]
        overrides = {int(k): v for k, v in plan.get("as", {}).items()}
        skip = {int(k) for k in plan.get("skip", [])}
        repeat = {int(k): v for k, v in plan.get("repeat", {}).items()}
        sets = {int(k): v for k, v in plan.get("set", {}).items()}
        qsets = {int(k): v for k, v in plan.get("query", {}).items()}
        raws = {int(k): v for k, v in plan.get("raw", {}).items()}
        trace = plan.get("trace", False)
        tenants = {self.tenant(actor)} | {self.tenant(u) for u in overrides.values() if u}
        res = RunResult()
        for t in tenants:
            res.before[t] = self.balance(t) if self.sem.balance else 0.0
        results: dict[int, StepResult] = {}
        for i, st in enumerate(journey["steps"]):
            who = overrides.get(i, actor) if i in overrides else actor
            if i in skip:
                res.steps.append(StepResult(i, st["method"], st["template"], who, skipped="skipped by plan"))
                continue
            owner_tenant = self.tenant(actor)
            try:
                path = "/" + "/".join(str(self._resolve(s, results, owner_tenant, res.canaries, False)) for s in st["path"])
                q = [(k, self._resolve(v, results, owner_tenant, res.canaries, False)) for k, v in st["query"]]
                body = self._resolve(st["body"], results, owner_tenant, res.canaries, canary=st["method"] == "POST" and who == actor)
            except (KeyError, IndexError, TypeError):
                res.steps.append(StepResult(i, st["method"], st["template"], who, skipped="unresolved reference"))
                continue
            if i in qsets:
                q = [(k, qsets[i].get(k, v)) for k, v in q]
            if i in sets and isinstance(body, dict):
                body = {**body, **sets[i]}
            elif i in sets and body is None:
                body = dict(sets[i])
            body = {k: v for k, v in body.items() if v is not None} if isinstance(body, dict) else body
            url = self.base + path + ("?" + urlencode(q) if q else "")
            for rep in range(repeat.get(i, 1)):
                kwargs = {"raw_body": raws[i]} if i in raws else {"json_body": body}
                r = self.gate.request(st["method"], url, headers=self.auth(who if (st["auth"] or who != actor) else None),
                                      actor=who or "anonymous", expect_error=i in raws, **kwargs)
                try:
                    js = r.json()
                except Exception:
                    js = None
                sr = StepResult(i, st["method"], url, who, r.status_code, js, r.text[:200000], request_body=raws.get(i, body),
                                modified=i in overrides or i in sets or i in qsets or i in raws or rep > 0)
                if trace and st["method"] != "GET":
                    sr.balance_after = {t: self.balance(t) for t in tenants}
                res.steps.append(sr)
                if rep == 0 or (200 <= r.status_code < 300):
                    results[i] = sr if 200 <= r.status_code < 300 else results.get(i, StepResult(i, "", "", None))
                if 200 <= r.status_code < 300 and st["method"] == "POST" and isinstance(js, dict):
                    for t in self.sem.types.values():
                        if t.creator == f"{st['method']} {st['template']}":
                            try:
                                oid = js
                                for key in t.id_path:
                                    oid = oid[key]
                                res.created.append((t.name, oid, self.tenant(who)))
                                self.gate.own(oid)
                            except Exception:
                                pass
        for t in tenants:
            res.after[t] = self.balance(t) if self.sem.balance else 0.0
        return res

    def cleanup(self, res: RunResult) -> None:
        """Release objects this run created that are still open (keeps test balances healthy)."""
        for tname, oid, tenant in res.created:
            t = self.sem.types[tname]
            if not t.release:
                continue
            owner = self.sem.accounts(tenant)[0]
            cur = self.read(t, oid, owner) or {}
            if cur.get(self.sem.model.status_field) not in (None, self.sem.terminal_status):
                self.gate.request(t.release.split(" ", 1)[0], self.base + t.release.split(" ", 1)[1].replace("{id}", oid), headers=self.auth(owner), actor=owner)


def graft(journey: dict, step: dict, name: str) -> dict:
    j = copy.deepcopy(journey)
    j["steps"].append(step)
    j["id"] = f"{journey['id']}+{name}"
    j["name"] = f"{journey['name']} + {name}"
    j["origin"] = "graft"
    return j


def synth_step(method: str, template: str, ref_idx: int, id_path: tuple, body_keys: list, creator_resp: dict) -> dict:
    """Build a step for an endpoint seen only in the bundle or by probing (no recorded traffic)."""
    path = [{"$ref": [ref_idx, list(id_path)]} if s == "{id}" else s for s in template.strip("/").split("/")]
    body = None
    if body_keys:
        body = {}
        for k in body_keys:
            if k in (creator_resp or {}) and isinstance(creator_resp[k], (int, float)) and not MONEY.search(k):
                body[k] = {"$ref": [ref_idx, [k]], "add": 1}  # change a configuration field by one unit
            # money keys are left to the server (control); operators tamper with them explicitly
    return {"method": method, "template": template, "auth": True, "har_status": 200, "path": path, "query": [], "body": body,
            "har_response": None, "synthetic": True, "money_keys": [k for k in body_keys if MONEY.search(k)]}


def dumps_journey(j: dict) -> str:
    return json.dumps({k: v for k, v in j.items()}, default=str)
