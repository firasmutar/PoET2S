"""Adaptive adversaries (v18): 30 seeds, static vs lie-and-recover vs stealth.

Uses the same slot harness as the main experiment, so the static condition
here is directly comparable with Table 6 (it differs only in seed count).
Writes results/adaptive.csv.
"""
from __future__ import annotations

import csv
import statistics as st
import sys
from pathlib import Path

from poet2s_sim.detection import run_protocol_slots

SEEDS = list(range(42, 72))          # 30 seeds
N, N_SLOTS, N_MAL = 500, 60, 75
REGIMES = {"static": False, "recover": True, "stealth": "stealth"}
SCHEMES = ["PoMonitor", "PoET2S"]
OUT = Path(__file__).resolve().parent.parent / "results" / "adaptive.csv"


def main() -> int:
    rows = []
    for scheme in SCHEMES:
        for reg, strat in REGIMES.items():
            for seed in SEEDS:
                r = run_protocol_slots(scheme, n_nodes=N, seed=seed, n_slots=N_SLOTS,
                                       strategic=strat)
                rows.append({"scheme": f"{scheme}-{reg}", "seed": seed,
                             "caught_pct": round(100 * r[-1].attackers_caught / N_MAL, 3),
                             "infiltration_pct": round(st.mean(x.infiltration_pct for x in r), 4),
                             "extracted_profit": round(sum(x.profit for x in r), 4)})
            sub = [x for x in rows if x["scheme"] == f"{scheme}-{reg}"]
            print(f"  {scheme}-{reg:8s} caught={st.mean(x['caught_pct'] for x in sub):5.1f} "
                  f"infil={st.mean(x['infiltration_pct'] for x in sub):5.2f} "
                  f"profit={st.mean(x['extracted_profit'] for x in sub):7.2f}", flush=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
