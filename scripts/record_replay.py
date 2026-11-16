"""Record a real run of the release train and write a static, replayable control room to site/.

    python -m scripts.record_replay        # -> site/index.html, site/replay.json, site/openapi.json

The site is what is published to GitHub Pages: nothing in it is staged or edited, it is the
event stream and state snapshots of an actual run (v3.0 baseline -> v3.1 deploy -> v3.1.1 hotfix).
"""
from __future__ import annotations

import copy
import json
import shutil
import time
from pathlib import Path

from paradox.engine import Bus, Engine
from target.app import State, serve

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
SNAP_ON = {"cycle", "learn", "finding", "resolved", "review", "deploy", "change", "safety"}


def slim(snap: dict) -> dict:
    s = copy.deepcopy(snap)
    for f in s["findings"]:
        f.pop("proof", None)
        for e in f.get("evidence", []):
            if "response" in e:
                e["response"] = e["response"][:240]
    return s


def main():
    st = State()
    st.reset()
    st.deploy("v3.0")
    serve(st, 8100, 8101)
    out = ROOT / "out_record"
    shutil.rmtree(out, ignore_errors=True)
    frames: list[dict] = []
    eng: Engine | None = None

    class RecBus(Bus):
        def emit(self, kind, msg, **kw):
            super().emit(kind, msg, **kw)
            ev = self.events[-1]
            fr = {"t": ev["ts"], "event": ev}
            if eng is not None and kind in SNAP_ON:
                fr["state"] = slim(eng.snapshot())
            frames.append(fr)

    eng = Engine(ROOT / "inputs", out, RecBus(echo=True), scope_override={"max_rps": 60})
    eng.release = "v3.0"
    frames.append({"t": time.time(), "state": slim(eng.snapshot())})
    eng.cycle("manual", release="v3.0")
    for rel in ("v3.1", "v3.1.1"):
        time.sleep(2)
        st.deploy(rel)
        ts = time.time()
        eng.bus.emit("deploy", f"Deploy webhook: b2b-portal {rel}", release=rel)
        eng.cycle("deploy", deploy_ts=ts, release=rel)
    frames.append({"t": time.time(), "state": slim(eng.snapshot())})

    SITE.mkdir(exist_ok=True)
    tickets = {p.stem: p.read_text(encoding="utf-8") for p in (out / "tickets").glob("*.md")}
    meta = {"recorded": time.strftime("%d %b %Y %H:%M"), "requests": eng.gate.sent,
            "description": f" Recorded {time.strftime('%d %b %Y')}: baseline on v3.0, then deploy v3.1 (new feature with a pricing bug), "
                           f"then hotfix v3.1.1. {eng.gate.sent:,} real requests to the synthetic sandbox."}
    (SITE / "replay.json").write_text(json.dumps({"meta": meta, "frames": frames, "tickets": tickets}, default=str), encoding="utf-8")
    shutil.copy(out / "openapi.json", SITE / "openapi.json")
    shutil.copy(ROOT / "paradox" / "ui.html", SITE / "index.html")
    (SITE / ".nojekyll").write_text("")
    shutil.rmtree(out, ignore_errors=True)
    print(f"site written: {len(frames)} frames, {len(tickets)} tickets, {(SITE / 'replay.json').stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
