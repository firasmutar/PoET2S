"""Main experiment (v18): 11 schemes x 30 seeds x 60 slots at N = 500.

Writes
  results/main_per_seed.csv   one row per (scheme, seed): every metric
  results/main_summary.csv    mean, SD, median, IQR and bootstrap 95% CI

All v18 paper numbers for Tables 6-8 come from these two files.
"""
from __future__ import annotations

import csv
import statistics as st
import sys
import time
from pathlib import Path

import numpy as np

from poet2s_sim.detection import run_protocol_slots

SCHEMES = ["PoW", "PoS", "PBFT", "DPoS", "PoS+Twin", "PBFT+Twin", "DPoS+Twin",
           "PoMonitor", "EACM", "RepStake", "PoET2S"]
SEEDS = list(range(42, 72))   # 30 seeds
N, N_SLOTS, MAL = 500, 60, 0.15
N_MAL = int(N * MAL)
RES = Path(__file__).resolve().parent.parent / "results"
METRICS = ["latency_ms", "caught_pct", "false_pos", "fp_per_caught",
           "infiltration_pct", "proposer_capture_pct", "profit", "msgs_per_block",
           "wall_clock_ms"]


def run_one(scheme: str, seed: int) -> dict:
    r = run_protocol_slots(scheme, n_nodes=N, seed=seed, n_slots=N_SLOTS)
    caught = r[-1].attackers_caught
    assert all(x.committed for x in r), (scheme, seed, "block not committed within the slot window")
    return {
        "scheme": scheme, "seed": seed,
        "latency_ms": st.mean(x.latency_ms for x in r),
        "caught_pct": 100.0 * caught / N_MAL,
        "false_pos": r[-1].false_pos_cum,
        "fp_per_caught": r[-1].false_pos_cum / max(caught, 1),
        "infiltration_pct": st.mean(x.infiltration_pct for x in r),
        "proposer_capture_pct": 100.0 * st.mean(x.proposer_malicious for x in r),
        "profit": sum(x.profit for x in r),
        "msgs_per_block": st.mean(x.msgs_sent for x in r),
        "wall_clock_ms": st.mean(x.wall_clock_ms for x in r),
        "t_q_proposal": st.mean([x.t_q_proposal for x in r if x.t_q_proposal is not None] or [float("nan")]),
        "t_q_prepared": st.mean([x.t_q_prepared for x in r if x.t_q_prepared is not None] or [float("nan")]),
    }


def bootstrap_ci(v, n_boot=2000, seed=0):
    rng = np.random.default_rng(seed)
    v = np.asarray(v, dtype=float)
    means = rng.choice(v, size=(n_boot, len(v)), replace=True).mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def main() -> int:
    t0 = time.time()
    rows = []
    for s in SCHEMES:
        for seed in SEEDS:
            rows.append(run_one(s, seed))
        print(f"  {s:10s} done ({time.time() - t0:.0f}s)", flush=True)
    keys = list(rows[0].keys())
    with open(RES / "main_per_seed.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    out = []
    for s in SCHEMES:
        for m in METRICS:
            v = [r[m] for r in rows if r["scheme"] == s]
            q1, q3 = np.percentile(v, [25, 75])
            lo, hi = bootstrap_ci(v)
            out.append({"scheme": s, "metric": m, "mean": st.mean(v), "sd": st.stdev(v),
                        "median": st.median(v), "q1": q1, "q3": q3, "ci_lo": lo, "ci_hi": hi})
    with open(RES / "main_summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        for r in out:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    print(f"wrote main_per_seed.csv, main_summary.csv in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
