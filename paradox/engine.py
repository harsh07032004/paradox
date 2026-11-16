"""Orchestrator: detect change -> learn -> plan -> execute safely -> verify -> triage -> report -> retest."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from paradox.hunt import Hunter
from paradox.recon import (AppModel, classify, fetch_bundle, learn_from_har, learn_from_logs, openapi, parse_bundle, probe,
                           strip_version, template_of)
from paradox.runner import Runner, Semantics
from paradox.safety import Gate, Halted, ScopeViolation
from paradox.triage import build_finding, ticket_md


class Bus:
    """In-process event stream for the dashboard (SSE) and logs."""

    def __init__(self, keep: int = 600, echo: bool = False):
        self.events: list[dict] = []
        self.keep, self.echo = keep, echo
        self.cv = threading.Condition()
        self.seq = 0

    def emit(self, kind: str, msg: str, **kw) -> None:
        with self.cv:
            self.seq += 1
            e = {"seq": self.seq, "ts": time.time(), "kind": kind, "msg": msg, **kw}
            self.events.append(e)
            self.events = self.events[-self.keep:]
            self.cv.notify_all()
        if self.echo:
            line = f"[{kind:>8}] {msg}"
            try:
                print(line, flush=True)
            except UnicodeEncodeError:  # legacy Windows consoles cannot print the rupee sign
                print(line.replace("₹", "INR ").encode("ascii", "replace").decode(), flush=True)

    def since(self, seq: int, timeout: float = 15) -> list[dict]:
        with self.cv:
            if self.seq <= seq:
                self.cv.wait(timeout)
            return [e for e in self.events if e["seq"] > seq]


class Engine:
    def __init__(self, inputs: Path, out: Path, bus: Bus | None = None, scope_override: dict | None = None):
        self.inputs, self.out = inputs, out
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "tickets").mkdir(exist_ok=True)
        self.scope = {**json.loads((inputs / "scope.json").read_text()), **(scope_override or {})}
        self.vault = {a["username"]: a for a in json.loads((inputs / "accounts.json").read_text())["accounts"]}
        self.ownership = json.loads((inputs / "ownership.json").read_text())
        self.base = self.scope["allowed_origins"][0].rstrip("/")
        self.bus = bus or Bus()
        self.gate = Gate(self.scope, out, self.bus)
        self.lock = threading.Lock()
        self.findings: dict[str, dict] = {}
        self.inventory: list[dict] = []
        self.review: list[dict] = []
        self.metrics = {"cycles": 0, "experiments": 0, "suppressed": 0, "duplicates": 0, "requests": 0, "last_ttf_s": None, "deploys": []}
        self.release = "unknown"
        self.model: AppModel | None = None
        self.sem = self.runner = self.hunter = None
        self.prev_sig: dict | None = None
        self.running = False

    # ------------------------------------------------------------------ learning
    def learn(self) -> set:
        """(Re)build the application model. Returns endpoint keys that are new or changed since last time."""
        t0 = time.time()
        self.gate.context = "recon"
        model = AppModel(self.base)
        js, h = fetch_bundle(self.gate, self.base)
        model.bundle_hash = h
        for method, tmpl, bkeys, qkeys in parse_bundle(js):
            ep = model.ep(method, tmpl)
            ep.sources.add("bundle")
            ep.body_keys.update(bkeys)
            ep.query_keys.update(qkeys)
            model.bundle_sig[ep.key] = sorted(bkeys)
        learn_from_har(model, json.loads((self.inputs / "har.json").read_text()), self.vault)
        learn_from_logs(model, self.inputs / "access_log.jsonl", self.scope.get("traffic_window_days", 90))
        sem = Semantics(model, self.vault)
        runner = Runner(sem, self.gate, self.base)
        hunter = Hunter(sem, runner, self.bus)
        if self.sem and self.sem.balance:
            sem.balance = self.sem.balance
        else:
            hunter.calibrate_ledger()
        # fresh objects to probe versioned routes with, then bounded probing
        sample = {}
        res = runner.run(sem.journeys[0])
        for tname, oid, _ in res.created:
            for c in sem.types[tname].consumers:
                sample[strip_version(c.split(" ", 1)[1])] = oid
        for j in sem.journeys:
            for st in j["steps"]:
                if "{id}" in st["template"] and strip_version(st["template"]) not in sample:
                    for seg in st["path"]:
                        if isinstance(seg, str) and template_of("/" + seg) == "/{id}":
                            sample[strip_version(st["template"])] = seg
        found = probe(model, self.gate, sample, runner.auth(sem.journeys[0]["user"]))
        runner.cleanup(res)
        changed = set()
        if self.prev_sig is not None:
            changed = {k for k, v in model.bundle_sig.items() if self.prev_sig.get(k) != v}
            gone = set(self.prev_sig) - set(model.bundle_sig)
            if changed or gone:
                self.bus.emit("change", f"Bundle diff: {len(changed)} new/changed route(s) {sorted(changed)}" + (f", {len(gone)} removed" if gone else ""))
        self.prev_sig = dict(model.bundle_sig)
        self.model, self.sem, self.runner, self.hunter = model, sem, runner, hunter
        self.inventory = classify(model, self.ownership, self.scope.get("traffic_window_days", 90), changed)
        (self.out / "openapi.json").write_text(json.dumps(openapi(model, self.inventory), indent=1))
        (self.out / "inventory.json").write_text(json.dumps(self.inventory, indent=1))
        counts = {}
        for r in self.inventory:
            counts[r["label"]] = counts.get(r["label"], 0) + 1
        parts = ", ".join(f"{v} {k}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
        self.bus.emit("learn", f"Learned {len(model.endpoints)} endpoints and {len(sem.journeys)} user journeys in {time.time()-t0:.1f}s "
                               f"({parts}). Probing found {len(found)} undocumented route(s).", inventory=counts)
        return changed

    # ------------------------------------------------------------------ cycle
    def cycle(self, trigger: str = "manual", deploy_ts: float | None = None, release: str | None = None) -> dict:
        with self.lock:
            self.running = True
            self.gate.new_cycle()
            if release:
                self.release = release
            start = deploy_ts or time.time()
            self.bus.emit("cycle", f"Cycle started ({trigger}{', release ' + release if release else ''})")
            stats = {"new": 0, "resolved": 0, "reopened": 0}
            try:
                changed = self.learn()
                focus = set(changed)
                stats["resolved"], stats["reopened"] = self.retest()
                extra = [ep for ep in self.model.endpoints.values() if ep.sources & {"probe", "bundle"} and "har" not in ep.sources]
                exps = self.hunter.plan(extra, focus)
                self.bus.emit("plan", f"Planned {len(exps)} targeted experiments" + (f"; {sum(1 for e in exps if e['endpoint'] in focus or any(f'{s['method']} {s['template']}' in focus for s in e['journey']['steps']))} touch changed routes, run first" if focus else ""))
                inv = {r["endpoint"]: r["label"] for r in self.inventory}
                for n, exp in enumerate(exps):
                    for v in self.hunter.execute(exp):
                        v["key"] = self.hunter.vkey(v)
                        if v["key"] in self.findings and self.findings[v["key"]]["status"] == "open":
                            self.metrics["duplicates"] += 1
                            continue
                        self.bus.emit("signal", f"Invariant broken? {v['summary']} [{exp['op']} @ {exp['endpoint']}]")
                        proof = self.hunter.verify(exp, v)
                        if not proof:
                            continue
                        ev = self.hunter.evidence(proof)
                        ttf = round(time.time() - start, 1)
                        prior = self.findings.get(v["key"])
                        fid = prior["id"] if prior else f"PDX-{len(self.findings) + 1:03d}"
                        f = build_finding(fid, v, proof, ev, inv, self.ownership, self.release,
                                          time.strftime("%Y-%m-%d %H:%M:%S"), ttf, self.base)
                        if prior:
                            f["history"] = prior["history"] + [{"at": f["detected_at"], "event": "reopened (regression)", "release": self.release}]
                            stats["reopened"] += 1
                        else:
                            stats["new"] += 1
                        self.findings[v["key"]] = f
                        self.metrics["last_ttf_s"] = self.metrics["last_ttf_s"] or ttf
                        (self.out / "tickets" / f"{fid}.md").write_text(ticket_md(f, self.base), encoding="utf-8")
                        self.bus.emit("finding", f"{f['severity']}: {f['headline']}", finding=fid, ttf=ttf, severity=f["severity"])
                    if n % 20 == 0:
                        self.bus.emit("progress", f"{n+1}/{len(exps)} experiments", done=n + 1, total=len(exps))
                self.review = self.hunter.review
            except Halted as h:
                self.bus.emit("safety", f"Cycle halted: {h}", level="error")
            except ScopeViolation as s:
                self.bus.emit("safety", f"Cycle stopped on scope rule: {s}", level="error")
            finally:
                self.metrics["cycles"] += 1
                self.metrics["experiments"] += self.hunter.experiments_run if self.hunter else 0
                self.metrics["suppressed"] += self.hunter.suppressed if self.hunter else 0
                self.metrics["requests"] = self.gate.sent
                self.running = False
                self.save()
            dur = round(time.time() - start, 1)
            self.bus.emit("cycle", f"Cycle done in {dur}s: {stats['new']} new, {stats['resolved']} resolved, {stats['reopened']} reopened. "
                                   f"{self.gate.sent} requests total.", stats=stats)
            return {**stats, "seconds": dur}

    def retest(self) -> tuple[int, int]:
        resolved = 0
        for f in self.findings.values():
            if f["status"] != "open":
                continue
            reproduced, clean_runs = 0, 0
            for _ in range(2):
                try:
                    if any(self.hunter.vkey(v) == f["key"] for v in self.hunter.execute(self.rebind(f["proof"]))):
                        reproduced += 1
                    else:
                        clean_runs += 1
                except (Halted, ScopeViolation):
                    raise
                except Exception as exc:  # an error is never evidence of a fix
                    self.bus.emit("retest", f"Retest of {f['id']} inconclusive ({type(exc).__name__}); kept open", level="warn")
            if reproduced == 0 and clean_runs == 2:
                f["status"] = "resolved"
                f["history"].append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "event": "retest passed, closed", "release": self.release})
                resolved += 1
                (self.out / "tickets" / f"{f['id']}.md").write_text(ticket_md(f, self.base), encoding="utf-8")
                self.bus.emit("resolved", f"Fixed and verified, closed {f['id']}: {f.get('headline', f['title'])}", finding=f["id"])
        return resolved, 0

    def rebind(self, proof: dict) -> dict:
        return proof  # proofs are journey templates; they rebind to fresh objects on every run

    # ------------------------------------------------------------------ persistence
    def snapshot(self) -> dict:
        return {
            "release": self.release, "running": self.running, "base": self.base,
            "findings": [dict(f) for f in sorted(self.findings.values(), key=lambda f: (f["status"] != "open", -f["score"]))],
            "inventory": self.inventory, "review": self.review,
            "metrics": {**self.metrics, "requests": self.gate.sent, "refused": self.gate.refused, "rps_cap": self.gate.rps,
                        "killed": self.gate.killed(), "paused": self.gate.paused_reason},
        }

    def save(self) -> None:
        snap = self.snapshot()
        for f in snap["findings"]:
            f = dict(f)
        (self.out / "state.json").write_text(json.dumps(snap, indent=1, default=str))
