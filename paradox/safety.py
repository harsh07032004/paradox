"""Safety layer. Every byte Paradox sends goes through `Gate.request`.

Rules enforced in code (not in prompts):
  * scope allowlist: exact scheme://host:port, anything else is refused and logged
  * own-object rule: state-changing calls may only reference object ids Paradox created
  * token-bucket rate limit, request budget per cycle
  * health monitor: backs off on latency spikes or 5xx streaks, halts if strain persists
  * kill switch: file `out/KILL` or the dashboard button stops everything instantly
  * audit log: every request (and every refusal) appended to out/audit.jsonl, replayable
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

import httpx


class Halted(Exception):
    """Raised when the kill switch is on, the budget is spent or health monitor stops the run."""


class ScopeViolation(Exception):
    pass


ID_SEG = re.compile(r"^(?!v\d+$)(?:(?=.*\d)[A-Za-z0-9_-]{3,}|[A-Z0-9]{5,}|[0-9a-fA-F-]{32,36})$")
SECRET_FIELDS = {"password", "pass", "secret", "otp"}


class Gate:
    def __init__(self, scope: dict, out_dir: Path, bus=None):
        self.allowed = {self._origin(u) for u in scope["allowed_origins"]}
        self.rps = float(scope.get("max_rps", 20))
        self.budget = int(scope.get("max_requests_per_cycle", 6000))
        self.out = out_dir
        self.out.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.out / "audit.jsonl"
        self.kill_file = self.out / "KILL"
        self.bus = bus
        self.client = httpx.Client(timeout=10)
        self.lock = threading.Lock()
        self.tokens, self.last = self.rps, time.monotonic()
        self.latency = deque(maxlen=40)
        self.baseline_latency: float | None = None
        self.err_streak = 0
        self.sent = 0
        self.refused = 0
        self.backoffs = 0
        self.strain = 0
        self.healthy_run = 0
        self.owned_ids: set[str] = set()
        self.context = "-"
        self.paused_reason: str | None = None

    @staticmethod
    def _origin(url: str) -> str:
        p = urlsplit(url)
        return f"{p.scheme}://{p.hostname}:{p.port or (443 if p.scheme == 'https' else 80)}"

    # ---------------------------------------------------------------- controls
    def killed(self) -> bool:
        return self.kill_file.exists()

    def kill(self, on: bool = True) -> None:
        if on:
            self.kill_file.write_text(str(time.time()))
        elif self.kill_file.exists():
            self.kill_file.unlink()

    def new_cycle(self) -> None:
        self.sent_cycle_start = self.sent

    def own(self, *ids: str) -> None:
        self.owned_ids.update(i for i in ids if i)

    # ---------------------------------------------------------------- core
    def _throttle(self) -> None:
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.rps, self.tokens + (now - self.last) * self.rps)
            self.last = now
            if self.tokens < 1:
                wait = (1 - self.tokens) / self.rps
                time.sleep(wait)
                self.tokens = 0
                self.last = time.monotonic()
            else:
                self.tokens -= 1

    def _health(self, status: int, secs: float, expect_error: bool) -> None:
        self.latency.append(secs)
        if self.baseline_latency is None and len(self.latency) >= 15:
            self.baseline_latency = max(sorted(self.latency)[len(self.latency) // 2], 0.004)
        self.err_streak = self.err_streak + 1 if (status >= 500 and not expect_error) else 0
        strained = False
        if self.baseline_latency and len(self.latency) >= 10:
            recent = sorted(list(self.latency)[-10:])[5]
            strained = recent > max(8 * self.baseline_latency, 0.25)
        if self.err_streak >= 5 or strained:
            self.backoffs += 1          # total back-off events (reported)
            self.strain += 1            # consecutive strain level (escalates)
            self.healthy_run = 0
            reason = "5xx streak" if self.err_streak >= 5 else f"latency {recent*1000:.0f}ms vs baseline {self.baseline_latency*1000:.0f}ms"
            self.paused_reason = reason
            self._emit("safety", f"Target under strain ({reason}). Backing off {min(2 ** self.strain, 16)}s.", level="warn")
            time.sleep(min(2 ** self.strain, 16))
            self.latency.clear()
            self.err_streak = 0
            if self.strain >= 4:
                self._emit("safety", "Strain persisted after 4 back-offs. Halting and handing over to a human.", level="error")
                raise Halted("target health")
        else:
            self.paused_reason = None
            self.healthy_run += 1
            if self.healthy_run >= 50:  # only sustained health forgives earlier strain
                self.strain, self.healthy_run = max(0, self.strain - 1), 0

    def _emit(self, kind, msg, **kw):
        if self.bus:
            self.bus.emit(kind, msg, **kw)

    def _audit(self, rec: dict) -> None:
        with self.lock, open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")

    @staticmethod
    def _redact(body):
        if isinstance(body, dict):
            return {k: ("***" if k.lower() in SECRET_FIELDS else Gate._redact(v)) for k, v in body.items()}
        if isinstance(body, list):
            return [Gate._redact(v) for v in body]
        return body

    def request(self, method: str, url: str, token: str | None = None, json_body=None, raw_body: str | None = None,
                headers: dict | None = None, expect_error: bool = False, actor: str = "-") -> httpx.Response:
        origin = self._origin(url)
        path = urlsplit(url).path
        rec = {"ts": time.time(), "ctx": self.context, "actor": actor, "method": method, "url": url,
               "body": self._redact(json_body) if json_body is not None else raw_body}
        if self.killed():
            raise Halted("kill switch")
        if origin not in self.allowed:
            self.refused += 1
            self._audit({**rec, "refused": "out of scope"})
            self._emit("safety", f"Refused out-of-scope request to {origin}", level="warn")
            raise ScopeViolation(origin)
        if method not in ("GET", "HEAD", "OPTIONS"):
            foreign = [s for s in path.split("/") if ID_SEG.match(s) and len(s) >= 4 and s not in self.owned_ids]
            if foreign:
                self.refused += 1
                self._audit({**rec, "refused": f"object {foreign[0]} not created by Paradox"})
                raise ScopeViolation(f"foreign object {foreign[0]}")
        if self.sent - getattr(self, "sent_cycle_start", 0) >= self.budget:
            raise Halted("request budget")
        self._throttle()
        h = dict(headers or {})
        if token:
            h["Authorization"] = f"Bearer {token}"
        t0 = time.monotonic()
        if raw_body is not None:
            h.setdefault("Content-Type", "application/json")
            r = self.client.request(method, url, content=raw_body, headers=h)
        else:
            r = self.client.request(method, url, json=json_body, headers=h)
        secs = time.monotonic() - t0
        self.sent += 1
        self._audit({**rec, "status": r.status_code, "ms": round(secs * 1000, 1),
                     "resp_sha": hashlib.sha1(r.content).hexdigest()[:12], "resp": r.text[:300]})
        self._health(r.status_code, secs, expect_error)
        return r
