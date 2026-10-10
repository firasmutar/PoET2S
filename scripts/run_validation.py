"""Network-model validation against established results.

A custom simulator is only trustworthy if it reproduces results that an
independent, authoritative source establishes. This script runs two such
checks and reports the fit quantitatively.

VALIDATION 1 - PBFT message complexity vs Castro-Liskov (1999).
The canonical result: in PBFT normal-case operation the primary sends V-1
pre-prepares, the V-1 backups each send a prepare to the other V-1 replicas,
(V-1)^2 messages, and all V replicas send a commit to the other V-1, V(V-1)
messages. The total is

    M_theory(V) = (V - 1) + (V - 1)^2 + V(V - 1) = 2V(V - 1),

which is O(V^2). This is the result every correct PBFT implementation must
reproduce (Castro & Liskov, OSDI 1999; see also the consensus surveys). We
run our simulator's PBFT at a range of network sizes, extract the validator
count V and the measured message count, and compare to M_theory(V).

VALIDATION 2 - Pareto delay sampler vs its analytical moments.
Our link delay is one-way = Pareto(alpha=2, x_m=10ms) / 2. A Pareto(alpha,
x_m) has theoretical median x_m * 2^(1/alpha) and, for alpha>1, mean
alpha*x_m/(alpha-1). We draw a large sample from the simulator's own sampler
and check the empirical median and mean against these closed forms. This
validates that the delay model is implemented as specified, not merely
plausible.

Run from the repository root:
    python scripts/run_validation.py
"""
from __future__ import annotations

import random
import statistics
import sys
from pathlib import Path

import numpy as np

from poet2s_sim.grid_model import build_grid
from poet2s_sim.protocols import CONSENSUS_CLASSES
from poet2s_sim.sim_core import DEScheduler, Network

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def pbft_validator_count(n_nodes: int, seed: int = 42) -> int:
    """Count nodes the simulator assigns the PBFT validator role."""
    rng = random.Random(seed)
    nodes = build_grid(n_nodes, 0.15, rng)
    return sum(1 for n in nodes if n.role == "validator")


def measure_pbft_messages(n_nodes: int, seed: int = 42) -> int:
    cls = CONSENSUS_CLASSES["PBFT"]
    rng = random.Random(seed)
    nodes = build_grid(n_nodes, 0.15, rng)
    sched = DEScheduler()
    net = Network(sched, n_nodes, rng=random.Random(seed + 1000))
    proto = cls(sched, net, nodes, None, rng=random.Random(seed + 2000))
    proto.propose_block()
    sched.run_until(120_000.0)
    return net.messages_sent


def theory_pbft_messages(v: int) -> int:
    # (V-1) pre-prepares + (V-1)^2 prepares from the backups + V(V-1) commits = 2V(V-1).
    # (The first submission used 2V^2 - V - 1, which also counts a prepare from the primary.)
    return (v - 1) + (v - 1) ** 2 + v * (v - 1)


def validate_pbft():
    print("=" * 66)
    print("VALIDATION 1: PBFT message complexity vs Castro-Liskov (1999)")
    print("  theory: M(V) = (V-1) + (V-1)^2 + V(V-1) = 2V(V-1)   [O(V^2)]")
    print("=" * 66)
    print(f"{'N':>6s} {'V':>5s} {'measured':>10s} {'theory':>10s} {'ratio':>7s} {'err%':>7s}")
    ns = [60, 100, 250, 500, 1000, 2000]
    ratios, errs = [], []
    rows = []
    for n in ns:
        v = pbft_validator_count(n)
        measured = measure_pbft_messages(n)
        theory = theory_pbft_messages(v)
        ratio = measured / theory if theory else float("nan")
        err = abs(measured - theory) / theory * 100 if theory else float("nan")
        ratios.append(ratio)
        errs.append(err)
        rows.append((n, v, measured, theory, ratio, err))
        print(f"{n:>6d} {v:>5d} {measured:>10d} {theory:>10d} {ratio:>7.3f} {err:>6.1f}%")

    # Fit measured ~ a*V^2 to confirm the quadratic exponent empirically.
    vs = np.array([r[1] for r in rows], dtype=float)
    ms = np.array([r[2] for r in rows], dtype=float)
    # log-log slope = empirical exponent
    slope, intercept = np.polyfit(np.log(vs), np.log(ms), 1)
    print(f"\n  empirical exponent (log-log slope): {slope:.3f}  (theory = 2.000)")
    print(f"  mean |error| vs theory: {statistics.mean(errs):.1f}%")
    print(f"  mean measured/theory ratio: {statistics.mean(ratios):.3f}")
    verdict = ("PASS" if abs(slope - 2.0) < 0.1 and statistics.mean(errs) < 15
               else "REVIEW")
    print(f"  VERDICT: {verdict} "
          f"(quadratic exponent within 0.1 of 2.0 and mean error < 15%)")
    return verdict


def validate_pareto():
    print("\n" + "=" * 66)
    print("VALIDATION 2: Pareto delay sampler vs analytical moments")
    print("  one-way delay = Pareto(alpha=2, x_m=10ms) / 2")
    print("=" * 66)
    sched = DEScheduler()
    net = Network(sched, n_nodes=2, rng=random.Random(7))
    samples = np.array([net._rtt_ms() for _ in range(200_000)])  # one-way (already /2)
    # Pareto(alpha, x_m): median = x_m * 2^(1/alpha); mean = alpha*x_m/(alpha-1)
    alpha, x_m = 2.0, 10.0
    full_median = x_m * 2 ** (1 / alpha)
    full_mean = alpha * x_m / (alpha - 1)
    th_median, th_mean = full_median / 2, full_mean / 2  # one-way = /2
    emp_median, emp_mean = float(np.median(samples)), float(np.mean(samples))
    print(f"{'moment':>10s} {'theory':>10s} {'empirical':>10s} {'err%':>7s}")
    med_err = abs(emp_median - th_median) / th_median * 100
    mean_err = abs(emp_mean - th_mean) / th_mean * 100
    print(f"{'median':>10s} {th_median:>10.3f} {emp_median:>10.3f} {med_err:>6.1f}%")
    print(f"{'mean':>10s} {th_mean:>10.3f} {emp_mean:>10.3f} {mean_err:>6.1f}%")
    # mean has heavy-tail sampling variance; median is the robust check
    verdict = "PASS" if med_err < 2.0 and mean_err < 10.0 else "REVIEW"
    print(f"  VERDICT: {verdict} (median within 2%, mean within 10%)")
    return verdict


def main() -> int:
    v1 = validate_pbft()
    v2 = validate_pareto()
    print("\n" + "=" * 66)
    print(f"SUMMARY: PBFT-complexity {v1}, Pareto-sampler {v2}")
    print("=" * 66)
    return 0 if v1 == "PASS" and v2 == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
