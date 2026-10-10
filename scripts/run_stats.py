"""Statistics and composite ranking (v18).

Reads the per-seed CSVs and writes
  results/stats_tests.csv        every pairwise test reported in the paper:
                                 wins, mean paired difference with bootstrap
                                 95% CI, exact two-sided Wilcoxon p, and the
                                 Holm-adjusted p over the whole table
  results/infiltration_pairs.csv per-seed infiltration, PoET2S vs each
                                 twin design point
  results/composite_matrix.csv   normalised decision matrix (twin family only)
  results/composite_scores.csv   equal-weight and TOPSIS scores + weights
  results/composite_loo.csv      leave-one-metric-out ranking
  results/composite_simplex.csv  share of the weight simplex on which each
                                 scheme ranks first

Why the signed-rank test: 30 matched seeds, bounded and often skewed metrics
(percentages, counts with floors), and no reason to assume normal paired
differences. scipy computes the exact null distribution when there are no ties or
zero differences and a normal approximation otherwise. The paired t-test p-value is
reported alongside for comparison.
"""
from __future__ import annotations

import csv
import itertools
import math
import statistics as st
import sys
from pathlib import Path

import numpy as np
from scipy.stats import ttest_rel, wilcoxon

RES = Path(__file__).resolve().parent.parent / "results"


def load(name):
    return list(csv.DictReader(open(RES / name)))


def col(rows, key, val, metric, sort_key="seed"):
    sub = sorted((r for r in rows if r[key] == val), key=lambda r: int(r[sort_key]))
    return [float(r[metric]) for r in sub]


def boot_ci(d, n=5000, seed=0):
    rng = np.random.default_rng(seed)
    d = np.asarray(d, float)
    m = rng.choice(d, size=(n, len(d)), replace=True).mean(axis=1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def test(family, a_name, b_name, metric, a, b, lower_better=True):
    d = np.asarray(a) - np.asarray(b)
    wins = int(np.sum(d < 0)) if lower_better else int(np.sum(d > 0))
    if np.allclose(d, 0):
        p, pt = 1.0, 1.0
    else:
        # round the paired differences so that values equal up to floating-point noise
        # (e.g. 1/21 vs 2/21 seat steps) form proper ties in the signed-rank test
        dr = np.round(d, 9)
        p = float(wilcoxon(dr, method="exact" if len(a) <= 25 else "auto").pvalue)
        pt = float(ttest_rel(a, b).pvalue)
    lo, hi = boot_ci(d)
    return {"family": family, "comparison": f"{a_name} vs {b_name}", "metric": metric,
            "n": len(a), "wins": wins, "mean_a": float(np.mean(a)), "mean_b": float(np.mean(b)),
            "mean_diff": float(np.mean(d)), "ci_lo": lo, "ci_hi": hi,
            "rel_change_pct": 100 * float(np.mean(d)) / float(np.mean(b)) if np.mean(b) else float("nan"),
            "p_wilcoxon": p, "p_ttest": pt}


def holm(ps):
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adj, running = [0.0] * len(ps), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(ps) - rank) * ps[i]))
        adj[i] = running
    return adj


def main() -> int:
    main_rows = load("main_per_seed.csv")
    tests = []
    P = lambda s, m: col(main_rows, "scheme", s, m)
    # F1: timing and detection cost vs classical baselines
    for b in ["PoS", "PBFT", "DPoS", "PoS+Twin", "PBFT+Twin", "DPoS+Twin"]:
        tests.append(test("baselines", "PoET2S", b, "latency_ms", P("PoET2S", "latency_ms"), P(b, "latency_ms")))
        tests.append(test("baselines", "PoET2S", b, "fp_per_caught", P("PoET2S", "fp_per_caught"), P(b, "fp_per_caught")))
    # F2: twin design points
    for b in ["PoMonitor", "EACM", "RepStake"]:
        tests.append(test("twin", "PoET2S", b, "infiltration_pct", P("PoET2S", "infiltration_pct"), P(b, "infiltration_pct")))
        tests.append(test("twin", "PoET2S", b, "proposer_capture_pct", P("PoET2S", "proposer_capture_pct"), P(b, "proposer_capture_pct")))
        tests.append(test("twin", "PoET2S", b, "caught_pct", P("PoET2S", "caught_pct"), P(b, "caught_pct"), lower_better=False))
        tests.append(test("twin", "PoET2S", b, "fp_per_caught", P("PoET2S", "fp_per_caught"), P(b, "fp_per_caught")))
    # F3: adaptive adversaries (30 seeds)
    if (RES / "adaptive.csv").exists():
        ad = load("adaptive.csv")
        for reg in ["static", "recover", "stealth"]:
            for m in ["infiltration_pct", "extracted_profit"]:
                tests.append(test("adaptive", f"PoET2S-{reg}", f"PoMonitor-{reg}", m,
                                  col(ad, "scheme", f"PoET2S-{reg}", m), col(ad, "scheme", f"PoMonitor-{reg}", m)))
            tests.append(test("adaptive", f"PoET2S-{reg}", f"PoMonitor-{reg}", "caught_pct",
                              col(ad, "scheme", f"PoET2S-{reg}", "caught_pct"),
                              col(ad, "scheme", f"PoMonitor-{reg}", "caught_pct"), lower_better=False))
    # F4: hybrid detector
    if (RES / "hybrid_ablation.csv").exists():
        hy = load("hybrid_ablation.csv")
        c = lambda v, m: col(hy, "variant", v, m)
        tests.append(test("hybrid", "PoET2S-hybrid", "PoMonitor", "caught_pct", c("PoET2S-hybrid", "caught_pct"),
                          c("PoMonitor", "caught_pct"), lower_better=False))
        tests.append(test("hybrid", "PoET2S-hybrid", "PoMonitor", "fp_per_caught", c("PoET2S-hybrid", "fp_per_caught"),
                          c("PoMonitor", "fp_per_caught")))
    adj = holm([t["p_wilcoxon"] for t in tests])
    for t, a in zip(tests, adj):
        t["p_holm"] = a
    with open(RES / "stats_tests.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(tests[0]))
        w.writeheader()
        for t in tests:
            w.writerow({k: (float(f"{v:.6g}") if isinstance(v, float) else v) for k, v in t.items()})
    print(f"{len(tests)} tests; Holm over the whole table")
    for t in tests:
        print(f"  [{t['family']:9s}] {t['comparison']:34s} {t['metric']:21s} wins {t['wins']:2d}/{t['n']} "
              f"diff {t['mean_diff']:+9.3f} [{t['ci_lo']:+.3f},{t['ci_hi']:+.3f}] p={t['p_wilcoxon']:.4g} holm={t['p_holm']:.4g}")

    # per-seed infiltration pairs
    seeds = sorted({int(r["seed"]) for r in main_rows})
    with open(RES / "infiltration_pairs.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["seed", "PoET2S", "RepStake", "EACM", "PoMonitor"])
        cols = {s: P(s, "infiltration_pct") for s in ["PoET2S", "RepStake", "EACM", "PoMonitor"]}
        for i, s in enumerate(seeds):
            w.writerow([s] + [round(cols[k][i], 3) for k in ["PoET2S", "RepStake", "EACM", "PoMonitor"]])

    # composite over the twin family on the three metrics that differ within it
    fam = ["PoMonitor", "EACM", "RepStake", "PoET2S"]
    metrics = [("caught_pct", True), ("fp_per_caught", False), ("infiltration_pct", False)]
    X = np.array([[st.mean(P(s, m)) for m, _ in metrics] for s in fam])
    N = np.zeros_like(X)
    for j, (_, higher) in enumerate(metrics):
        lo, hi = X[:, j].min(), X[:, j].max()
        N[:, j] = (X[:, j] - lo) / (hi - lo) if higher else (hi - X[:, j]) / (hi - lo)
    with open(RES / "composite_matrix.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scheme"] + [f"{m}_raw" for m, _ in metrics] + [f"{m}_norm" for m, _ in metrics])
        for i, s in enumerate(fam):
            w.writerow([s] + [round(v, 4) for v in X[i]] + [round(v, 4) for v in N[i]])

    def topsis(X, wts, dirs):
        R = X / np.sqrt((X ** 2).sum(axis=0))
        V = R * wts
        best = np.where(dirs, V.max(axis=0), V.min(axis=0))
        worst = np.where(dirs, V.min(axis=0), V.max(axis=0))
        dp = np.sqrt(((V - best) ** 2).sum(axis=1))
        dm = np.sqrt(((V - worst) ** 2).sum(axis=1))
        return dm / (dp + dm)

    dirs = np.array([h for _, h in metrics])
    w_eq = np.array([1 / 3] * 3)
    eq = N @ w_eq
    tp = topsis(X, w_eq, dirs)
    with open(RES / "composite_scores.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scheme", "equal_weight", "topsis", "w_caught", "w_fpc", "w_infil"])
        for i, s in enumerate(fam):
            w.writerow([s, round(eq[i], 4), round(tp[i], 4)] + [round(x, 4) for x in w_eq])
    print("\ncomposite (twin family, 3 metrics, equal weights 1/3):")
    for i, s in enumerate(fam):
        print(f"  {s:10s} equal={eq[i]:.3f} topsis={tp[i]:.3f}")

    # leave-one-metric-out
    with open(RES / "composite_loo.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dropped", "scheme", "equal_weight", "topsis", "rank_equal"])
        print("\nleave-one-metric-out:")
        for j, (m, _) in enumerate(metrics):
            keep = [k for k in range(3) if k != j]
            wk = np.array([0.5, 0.5])
            e = N[:, keep] @ wk
            t = topsis(X[:, keep], wk, dirs[keep])
            ranks = (-e).argsort().argsort() + 1
            for i, s in enumerate(fam):
                w.writerow([m, s, round(e[i], 4), round(t[i], 4), int(ranks[i])])
            print(f"  drop {m:17s}: " + ", ".join(f"{fam[i]}={e[i]:.2f}" for i in (-e).argsort()))

    # weight simplex sweep (step 0.02)
    counts = {s: 0 for s in fam}
    total = 0
    grid = np.round(np.arange(0, 1.0001, 0.02), 2)
    for a, b in itertools.product(grid, grid):
        if a + b > 1.0 + 1e-9:
            continue
        wv = np.array([a, b, 1 - a - b])
        counts[fam[int(np.argmax(N @ wv))]] += 1
        total += 1
    with open(RES / "composite_simplex.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scheme", "share_first_pct"])
        for s in fam:
            w.writerow([s, round(100 * counts[s] / total, 2)])
    print("\nshare of weight simplex ranked first: " + ", ".join(f"{s}={100*counts[s]/total:.1f}%" for s in fam))
    return 0


if __name__ == "__main__":
    sys.exit(main())
