"""Tests: safety rules, generality guard, end-to-end detection, retest after fix."""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

import httpx
import pytest

from paradox.engine import Bus, Engine
from paradox.safety import Gate, Halted, ScopeViolation
from target.app import State, serve
from target.mutants import matches

ROOT = Path(__file__).resolve().parents[1]
PORT = 8150


@pytest.fixture(scope="module")
def target():
    st = State()
    st.reset()
    st.deploy("v3.0")
    serve(st, PORT, PORT + 1)
    return st


def engine(tmp: Path, **scope) -> Engine:
    inp = tmp / "inputs"
    shutil.copytree(ROOT / "inputs", inp, dirs_exist_ok=True)
    sc = json.loads((inp / "scope.json").read_text())
    sc.update({"allowed_origins": [f"http://127.0.0.1:{PORT}"], "max_rps": 400, **scope})
    (inp / "scope.json").write_text(json.dumps(sc))
    return Engine(inp, tmp / "out", Bus())


# ------------------------------------------------------------------ generality guard
def test_agent_code_contains_no_target_knowledge():
    """The agent must learn the app; it may not hard-code the sandbox's routes, ids, names or bugs."""
    banned = [r"/api/v3", r"/api/v1", r"bookings", r"quotes", r"wallet", r"WB\d", r"AG100", r"AG200", r"Waypoint",
              r"WELCOME10", r"MONSOON5", r"markup", r"voucher", r"invoice", r"HELD", r"CONFIRMED", r"CANCELLED",
              r"pnr", r"SkyLane", r"M0\d", r"M1\d"]
    for name in ("safety.py", "recon.py", "runner.py", "hunt.py", "engine.py", "server.py"):  # decision logic (triage holds prose only)
        f = ROOT / "paradox" / name
        src = f.read_text(encoding="utf-8")
        for b in banned:
            assert not re.search(b, src), f"{f.name} contains target-specific token {b!r}"


# ------------------------------------------------------------------ safety
def test_out_of_scope_request_is_refused_and_logged(tmp_path, target):
    g = Gate({"allowed_origins": [f"http://127.0.0.1:{PORT}"], "max_rps": 50}, tmp_path)
    with pytest.raises(ScopeViolation):
        g.request("GET", f"http://127.0.0.1:{PORT + 1}/status")  # control plane is out of scope
    with pytest.raises(ScopeViolation):
        g.request("GET", "https://example.com/")
    log = [json.loads(x) for x in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert all(r.get("refused") == "out of scope" for r in log) and len(log) == 2


def test_kill_switch_halts_immediately(tmp_path, target):
    g = Gate({"allowed_origins": [f"http://127.0.0.1:{PORT}"], "max_rps": 50}, tmp_path)
    assert g.request("GET", f"http://127.0.0.1:{PORT}/internal/health").status_code == 200
    g.kill(True)
    with pytest.raises(Halted):
        g.request("GET", f"http://127.0.0.1:{PORT}/internal/health")
    g.kill(False)


def test_state_change_on_foreign_object_is_refused(tmp_path, target):
    g = Gate({"allowed_origins": [f"http://127.0.0.1:{PORT}"], "max_rps": 50}, tmp_path)
    with pytest.raises(ScopeViolation):
        g.request("POST", f"http://127.0.0.1:{PORT}/api/v3/bookings/WB99999/cancel")
    g.own("WB99999")
    assert g.request("POST", f"http://127.0.0.1:{PORT}/api/v3/bookings/WB99999/cancel").status_code == 401


def test_rate_limit_is_respected(tmp_path, target):
    g = Gate({"allowed_origins": [f"http://127.0.0.1:{PORT}"], "max_rps": 20}, tmp_path)
    g.tokens = 0
    t0 = time.monotonic()
    for _ in range(10):
        g.request("GET", f"http://127.0.0.1:{PORT}/internal/health")
    assert time.monotonic() - t0 >= 0.4  # 10 requests at 20 rps from an empty bucket


def test_backs_off_when_target_strains(tmp_path, target):
    g = Gate({"allowed_origins": [f"http://127.0.0.1:{PORT}"], "max_rps": 400}, tmp_path)
    for _ in range(20):
        g.request("GET", f"http://127.0.0.1:{PORT}/internal/health")
    target.load_delay = 0.3
    try:
        for _ in range(12):
            g.request("GET", f"http://127.0.0.1:{PORT}/internal/health")
        assert g.backoffs >= 1
    finally:
        target.load_delay = 0


def test_audit_redacts_passwords(tmp_path, target):
    g = Gate({"allowed_origins": [f"http://127.0.0.1:{PORT}"], "max_rps": 50}, tmp_path)
    g.request("POST", f"http://127.0.0.1:{PORT}/api/v3/auth/login", json_body={"username": "goa.sub", "password": "Sandbox#Goa2"})
    assert "Sandbox#Goa2" not in (tmp_path / "audit.jsonl").read_text()


# ------------------------------------------------------------------ end to end
def test_clean_release_has_no_false_positives(tmp_path, target):
    target.reset()
    target.deploy("v3.0", mutants=set())
    e = engine(tmp_path)
    e.cycle("test")
    fs = e.snapshot()["findings"]
    allowed = [f for f in fs if matches("Z01", f) or matches("Z02", f)]  # legacy surface exists in every release
    assert len(fs) == len(allowed), [f["title"] for f in fs]
    labels = {r["endpoint"]: r["label"] for r in e.inventory}
    assert labels["GET /api/v1/bookings/{id}"] == "zombie"
    assert labels["GET /api/v3/partner/rates"] == "shadow"
    assert labels["GET /api/v2/bookings/{id}"] == "retired"


def test_new_deploy_is_caught_and_fix_is_retested(tmp_path, target):
    target.reset()
    target.deploy("v3.0")
    e = engine(tmp_path)
    e.cycle("baseline", release="v3.0")
    target.deploy("v3.1")
    e.cycle("deploy", deploy_ts=time.time(), release="v3.1")
    amend = [f for f in e.snapshot()["findings"] if matches("AMEND", f)]
    assert amend and amend[0]["status"] == "open" and amend[0]["ttf_s"] < 60
    target.deploy("v3.1.1")
    e.cycle("deploy", deploy_ts=time.time(), release="v3.1.1")
    by_key = {f["key"]: f for f in e.snapshot()["findings"]}
    assert by_key[amend[0]["key"]]["status"] == "resolved"
    double_refund = [f for f in by_key.values() if matches("M04", f)]
    assert double_refund and double_refund[0]["status"] == "resolved"
    still = [f for f in by_key.values() if matches("M11", f)]
    assert still and still[0]["status"] == "open"  # M11 not fixed in v3.1.1, must stay open


def test_dashboard_polling_never_closes_real_findings(tmp_path, target):
    """Regression: the state endpoint once stripped proofs in place and the next retest closed every ticket."""
    from fastapi.testclient import TestClient
    from paradox.server import build
    target.reset()
    target.deploy("v3.0")
    e = engine(tmp_path)
    e.cycle("baseline", release="v3.0")
    client = TestClient(build(e))
    for _ in range(3):
        assert client.get("/api/state").status_code == 200
    assert all("proof" in f for f in e.findings.values())
    broken = next(iter(e.findings.values()))
    broken["proof"] = {"op": "plain", "journey": {"steps": []}}  # a proof that cannot run
    e.cycle("redeploy", release="v3.0")  # nothing fixed
    assert all(f["status"] == "open" for f in e.findings.values()), [f["title"] for f in e.findings.values() if f["status"] != "open"]


def test_every_finding_has_minimal_replayable_proof(tmp_path, target):
    target.reset()
    target.deploy("v3.1", mutants={"M03", "M05", "M09"})
    e = engine(tmp_path)
    e.cycle("test", release="v3.1")
    fs = e.snapshot()["findings"]
    assert fs
    for f in fs:
        if f["kind"] == "sql_injection":
            continue
        steps = [x for x in f["evidence"] if "request" in x]
        assert steps, f["title"]
        assert (e.out / "tickets" / f"{f['id']}.md").exists()
        assert len(steps) <= f["original_steps"] + 1
