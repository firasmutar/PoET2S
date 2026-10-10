"""Parameter sensitivity study for PoET2S.

Sweeps the four protocol parameters one at a time around their defaults,
measuring latency, throughput, detection rate, and false-positive cost at
each setting. Used to justify the default choices (K=21, gamma=2.5,
eta=0.22, tts_reject=0.35) and to show the protocol is not brittle.

Run from the repository root:
    python scripts/run_param_sensitivity.py
"""
from __future__ import annotations

import csv
import statistics
import sys
import time
from pathlib import Path

from poet2s_sim.detection import run_protocol_slots

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_CSV = RESULTS_DIR / "param_sensitivity.csv"

N = 500
N_SLOTS = 60          # match the main experiment horizon
SEEDS = list(range(42, 72))   # 30 seeds per setting (v19)
N_MAL = int(N * 0.15)

DEFAULTS = {
    "committee_size": 21,
    "gamma": 2.5,
    "eta": 0.22,
    "tts_reject": 0.35,
}

# Values to sweep for each parameter (default is included in each list).
SWEEPS = {
    "committee_size": [7, 15, 21, 31, 51],
    "gamma": [1.0, 1.5, 2.5, 3.5, 5.0],
    "eta": [0.05, 0.10, 0.22, 0.40, 0.60],
    "tts_reject": [0.20, 0.30, 0.35, 0.45, 0.60],
}


def evaluate(proto_kwargs: dict):
    """Run PoET2S at the given parameters over SEEDS; return aggregate metrics."""
    lats, tps, caught_pcts, fpcs, infil = [], [], [], [], []
    for seed in SEEDS:
        results = run_protocol_slots(
            "PoET2S", n_nodes=N, seed=seed, n_slots=N_SLOTS,
            detect_sample_size=150, proto_kwargs=proto_kwargs,
        )
        lats.append(statistics.mean(r.latency_ms for r in results))
        tps.append(statistics.mean(r.throughput_tps for r in results))
        caught = results[-1].attackers_caught
        caught_pcts.append(100.0 * caught / max(N_MAL, 1))
        fps = results[-1].false_pos_cum
        fpcs.append(fps / max(caught, 1))
        infil.append(statistics.mean(r.infiltration_pct for r in results))
    return {
        "latency_ms": statistics.mean(lats),
        "throughput_tps": statistics.mean(tps),
        "caught_pct": statistics.mean(caught_pcts),
        "fp_per_caught": statistics.mean(fpcs),
        "infiltration_pct": statistics.mean(infil),
    }


def main() -> int:
    print(f"Parameter sensitivity: N={N}, {len(SEEDS)} seeds, {N_SLOTS} slots/run")
    print(f"Defaults: {DEFAULTS}\n")

    rows = []
    t0 = time.time()
    for param, values in SWEEPS.items():
        print(f"== sweeping {param} ==")
        for v in values:
            kwargs = dict(DEFAULTS)
            kwargs[param] = v
            metrics = evaluate(kwargs)
            is_default = (v == DEFAULTS[param])
            rows.append({
                "parameter": param,
                "value": v,
                "is_default": is_default,
                **{k: round(val, 2) for k, val in metrics.items()},
            })
            flag = "  <-- default" if is_default else ""
            print(f"  {param}={v:<5} lat={metrics['latency_ms']:6.1f}ms "
                  f"tps={metrics['throughput_tps']:7.0f} "
                  f"caught={metrics['caught_pct']:5.1f}% "
                  f"FP/c={metrics['fp_per_caught']:5.1f}{flag}")
        print()

    with open(OUTPUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["parameter", "value", "is_default", "latency_ms", "throughput_tps", "caught_pct", "fp_per_caught", "infiltration_pct"],
        )
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {OUTPUT_CSV} ({time.time() - t0:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
