"""Paradox control room: dashboard, deploy webhook, live event stream, kill switch.

    python -m paradox.server            # agent on :9000, target taken from inputs/scope.json
    python -m scripts.demo              # sandbox + agent + scripted deploys, for the walkthrough
"""
from __future__ import annotations

import argparse
import asyncio
import json
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse

from paradox.engine import Bus, Engine

ROOT = Path(__file__).resolve().parents[1]


def build(engine: Engine, watch_secs: float = 0) -> FastAPI:
    app = FastAPI(title="Paradox", docs_url=None, redoc_url=None)
    queue: list = []
    cv = threading.Condition()

    def worker():
        while True:
            with cv:
                while not queue:
                    cv.wait()
                job = queue.pop(0)
            try:
                engine.cycle(**job)
            except Exception as exc:  # keep the agent alive; surface the error
                engine.bus.emit("error", f"Cycle crashed: {exc!r}", level="error")

    threading.Thread(target=worker, daemon=True).start()

    def enqueue(**job):
        with cv:
            if not any(j.get("trigger") == job.get("trigger") for j in queue):
                queue.append(job)
            cv.notify()

    if watch_secs:
        def watcher():
            last = None
            while True:
                time.sleep(watch_secs)
                try:
                    from paradox.recon import fetch_bundle
                    _, h = fetch_bundle(engine.gate, engine.base)
                    if last and h != last and not engine.running:
                        engine.bus.emit("change", f"Front-end bundle changed ({last} -> {h}) without a deploy hook. Re-testing.")
                        enqueue(trigger="bundle-diff", deploy_ts=time.time())
                    last = h
                except Exception:
                    pass
        threading.Thread(target=watcher, daemon=True).start()

    @app.get("/", response_class=HTMLResponse)
    def ui():
        return (ROOT / "paradox" / "ui.html").read_text(encoding="utf-8")

    @app.get("/api/state")
    def state():
        snap = engine.snapshot()
        snap["findings"] = [{k: v for k, v in f.items() if k != "proof"} for f in snap["findings"]]  # copies: never mutate engine state
        return JSONResponse(json.loads(json.dumps(snap, default=str)))

    @app.get("/api/events")
    async def events(request: Request, since: int = 0):
        async def gen():
            seq = since
            while not await request.is_disconnected():
                evs = await asyncio.to_thread(engine.bus.since, seq, 10)
                for e in evs:
                    seq = e["seq"]
                    yield f"data: {json.dumps(e, default=str)}\n\n"
                if not evs:
                    yield ": keepalive\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/hooks/deploy")
    async def deploy(request: Request):
        ev = await request.json()
        engine.metrics["deploys"].append(ev)
        engine.bus.emit("deploy", f"Deploy webhook: {ev.get('service', '?')} {ev.get('release', '?')}", release=ev.get("release"))
        enqueue(trigger="deploy", deploy_ts=float(ev.get("ts", time.time())), release=ev.get("release"))
        return {"queued": True}

    @app.post("/api/run")
    def run():
        enqueue(trigger="manual")
        return {"queued": True}

    @app.post("/api/kill")
    async def kill(request: Request):
        on = (await request.json()).get("on", True)
        engine.gate.kill(on)
        engine.bus.emit("safety", "KILL SWITCH ENGAGED: all agent traffic stopped." if on else "Kill switch released.", level="error" if on else "info")
        return {"killed": engine.gate.killed()}

    @app.get("/api/tickets/{fid}", response_class=PlainTextResponse)
    def ticket(fid: str):
        p = engine.out / "tickets" / f"{fid}.md"
        return p.read_text(encoding="utf-8") if p.exists() else PlainTextResponse("not found", 404)

    @app.get("/api/openapi.json")
    def spec():
        p = engine.out / "openapi.json"
        return FileResponse(p) if p.exists() else JSONResponse({}, 404)

    @app.get("/api/audit")
    def audit(n: int = 60):
        p = engine.out / "audit.jsonl"
        if not p.exists():
            return []
        lines = p.read_text(encoding="utf-8").splitlines()[-n:]
        return [json.loads(x) for x in lines]

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", default=str(ROOT / "inputs"))
    ap.add_argument("--out", default=str(ROOT / "out"))
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--watch", type=float, default=10, help="seconds between bundle-diff checks (0 = off)")
    ap.add_argument("--release", default="unknown", help="label of the release currently deployed")
    args = ap.parse_args()
    eng = Engine(Path(args.inputs), Path(args.out), Bus(echo=True))
    eng.gate.kill(False)
    eng.release = args.release
    app = build(eng, args.watch)
    print(f"Paradox control room: http://127.0.0.1:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
