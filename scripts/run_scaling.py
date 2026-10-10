"""Scaling sweep (v18): commit latency and messages per block versus N.

Each point is the mean over 3 seeds x 5 consecutive blocks (3 blocks at
N = 4000), run through the same slot harness as the main experiment, so the
N = 500 point is directly comparable with Table 6. Writes results/scaling.csv.
"""
from __future__ import annotations

import csv
import statistics as st
import sys
import time
from pathlib import Path

from poet2s_sim.detection import run_protocol_slots

N_VALUES = [100, 250, 500, 1000, 2000, 4000]
SCHEMES = ["PoS", "PBFT", "DPoS", "PoET2S"]
SEEDS = [42, 43, 44]
OUT = Path(__file__).resolve().parent.parent / "results" / "scaling.csv"


def main() -> int:
    rows, t0 = [], time.time()
    for n in N_VALUES:
        slots = 3 if n >= 4000 else 5
        for scheme in SCHEMES:
            lats, msgs, vsize = [], [], []
            for seed in SEEDS:
                r = run_protocol_slots(scheme, n_nodes=n, seed=seed, n_slots=slots,
                                       detect_sample_size=min(150, n))
                lats += [x.latency_ms for x in r]
                msgs += [x.msgs_sent for x in r]
            rows.append({"N": n, "scheme": scheme,
                         "latency_ms": round(st.mean(lats), 3),
                         "latency_sd": round(st.stdev(lats), 3),
                         "messages": round(st.mean(msgs), 1)})
            print(f"  N={n:5d} {scheme:7s} lat={st.mean(lats):7.2f} msgs={st.mean(msgs):9.0f} "
                  f"({time.time() - t0:.0f}s)", flush=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
