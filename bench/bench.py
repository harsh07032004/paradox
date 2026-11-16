"""Mutation benchmark: inject random unseen defects, run Paradox and the baseline, score both.

    python -m bench.bench --trials 12 --k 4 --seed 2026
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import statistics
import time
from pathlib import Path

from bench.baseline import run_baseline
from paradox.engine import Bus, Engine
from target.app import State, serve
from target.mutants import CATALOG, GROUND_TRUTH, matches

ROOT = Path(__file__).resolve().parents[1]


def score(active: list[str], findings: list[dict]) -> dict:
    detected = {d: any(matches(d, f) for f in findings) for d in active}
    tp_findings = [f for f in findings if any(matches(d, f) for d in active)]
    return {"detected": detected, "recall": sum(detected.values()) / len(active) if active else 1.0,
            "findings": len(findings), "false_positives": len(findings) - len(tp_findings),
            "fp_list": [f"{f['kind']} @ {f['endpoint']}" for f in findings if f not in tp_findings],
            "precision": len(tp_findings) / len(findings) if findings else 1.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=12)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--rps", type=float, default=400)
    args = ap.parse_args()
    rnd = random.Random(args.seed)
    st = State()
    st.reset()
    serve(st, 8100, 8101)
    pool = sorted(CATALOG)
    trials = [("clean", "v3.0", set())]
    for n in range(args.trials):
        trials.append((f"t{n+1:02d}", rnd.choice(["v3.0", "v3.1"]), set(rnd.sample(pool, args.k))))
    trials.append(("all-on", "v3.1", set(pool)))
    rows, per_defect = [], {d: {"paradox": [0, 0], "baseline": [0, 0]} for d in GROUND_TRUTH}
    for name, release, muts in trials:
        st.reset()
        st.deploy(release, muts)
        active = sorted(muts) + ["Z01", "Z02"] + (["AMEND"] if st.amend_bug else [])
        out = ROOT / "bench" / "runs" / name
        shutil.rmtree(out, ignore_errors=True)
        eng = Engine(ROOT / "inputs", out, Bus(), scope_override={"max_rps": args.rps, "max_requests_per_cycle": 20000})
        eng.release = release
        t0 = time.time()
        eng.cycle("bench", release=release)
        secs = time.time() - t0
        pf = eng.snapshot()["findings"]
        ttf = min([f["ttf_s"] for f in pf if f.get("ttf_s")] or [None]) if pf else None
        st.reset()
        st.deploy(release, muts)
        bf = run_baseline("http://127.0.0.1:8100", ROOT / "inputs")
        ps, bs = score(active, pf), score(active, bf)
        for d in active:
            per_defect[d]["paradox"][0] += ps["detected"][d]; per_defect[d]["paradox"][1] += 1
            per_defect[d]["baseline"][0] += bs["detected"][d]; per_defect[d]["baseline"][1] += 1
        row = {"trial": name, "release": release, "defects": active, "paradox": {**ps, "seconds": round(secs, 1), "requests": eng.gate.sent,
               "first_finding_s": ttf, "suppressed": eng.metrics["suppressed"]}, "baseline": bs}
        rows.append(row)
        missed = [d for d, ok in ps["detected"].items() if not ok]
        print(f"{name:7} {release:6} defects={len(active):2}  paradox recall={ps['recall']:.0%} prec={ps['precision']:.0%} "
              f"({ps['findings']} findings, {secs:.0f}s, {eng.gate.sent} req) missed={missed} fp={ps['fp_list']}  |  "
              f"baseline recall={bs['recall']:.0%} prec={bs['precision']:.0%} fp={len(bs['fp_list'])}", flush=True)

    def agg(tool):
        tot_det = sum(sum(r[tool]["detected"].values()) for r in rows)
        tot_act = sum(len(r[tool]["detected"]) for r in rows)
        tot_f = sum(r[tool]["findings"] for r in rows)
        tot_fp = sum(r[tool]["false_positives"] for r in rows)
        return {"recall": tot_det / tot_act, "precision": (tot_f - tot_fp) / tot_f if tot_f else 1, "defects_injected": tot_act,
                "defects_found": tot_det, "findings": tot_f, "false_positives": tot_fp}

    summary = {"paradox": agg("paradox"), "baseline": agg("baseline"),
               "paradox_median_cycle_s": statistics.median(r["paradox"]["seconds"] for r in rows),
               "paradox_median_first_finding_s": statistics.median([r["paradox"]["first_finding_s"] for r in rows if r["paradox"]["first_finding_s"]] or [0]),
               "per_defect": {d: {t: f"{v[t][0]}/{v[t][1]}" for t in v} for d, v in per_defect.items() if v["paradox"][1]},
               "trials": len(rows), "k": args.k, "seed": args.seed, "rps_cap": args.rps}
    (ROOT / "bench" / "results.json").write_text(json.dumps({"summary": summary, "trials": rows}, indent=1, default=str))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
