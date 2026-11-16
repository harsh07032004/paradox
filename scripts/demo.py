"""Live demo: sandbox platform + Paradox control room + a scripted release train.

    python -m scripts.demo            # opens http://127.0.0.1:9000, then:
      t=0     baseline cycle on v3.0 (production as it is today)
      t+N     deploy v3.1  (new 'amend booking' feature ships with a pricing bug)
      t+M     deploy v3.1.1 (hotfix: amend repriced server-side, double refund fixed)
    python -m scripts.demo --manual   # no scripted deploys; trigger them yourself:
      curl -X POST http://127.0.0.1:8101/deploy -H "Content-Type: application/json" -d "{\"release\": \"v3.1\"}"
"""
from __future__ import annotations

import argparse
import shutil
import threading
import time
from pathlib import Path

import httpx
import uvicorn

from paradox.engine import Bus, Engine
from paradox.server import build
from target.app import State, serve

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manual", action="store_true")
    ap.add_argument("--gap", type=float, default=25, help="seconds between scripted deploys")
    args = ap.parse_args()
    st = State()
    st.reset()
    st.deploy("v3.0")
    serve(st, 8100, 8101)
    out = ROOT / "out"
    shutil.rmtree(out, ignore_errors=True)
    eng = Engine(ROOT / "inputs", out, Bus(echo=True))
    eng.release = "v3.0"
    app = build(eng, watch_secs=0)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=9000, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    httpx.post("http://127.0.0.1:8101/hooks", json={"url": "http://127.0.0.1:9000/hooks/deploy"})
    print("Control room: http://127.0.0.1:9000")
    httpx.post("http://127.0.0.1:9000/api/run")
    if not args.manual:
        def train():
            for rel in ("v3.1", "v3.1.1"):
                time.sleep(3)
                while eng.running:
                    time.sleep(0.5)
                time.sleep(args.gap)
                print(f"\n=== DEPLOYING {rel} ===\n")
                httpx.post("http://127.0.0.1:8101/deploy", json={"release": rel})
        threading.Thread(target=train, daemon=True).start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
