"""Statistics for the v19 robustness runs. Writes results/stats_v19.csv."""
import csv, collections, statistics as st
from pathlib import Path
import numpy as np
from scipy.stats import wilcoxon
RES = Path(__file__).resolve().parent.parent / "results"
rows = []
def boot(d, n=5000):
    rng = np.random.default_rng(0)
    b = [rng.choice(d, len(d)).mean() for _ in range(n)]
    return np.percentile(b, [2.5, 97.5])
def test(family, comp, metric, a, b):
    a, b = np.asarray(a, float), np.asarray(b, float); d = a - b
    dr = np.round(d, 9)  # float-noise differences become proper ties
    p = wilcoxon(dr).pvalue if np.any(dr != 0) else 1.0
    lo, hi = boot(d)
    rows.append({"family": family, "comparison": comp, "metric": metric, "n": len(d), "wins": int((d < 0).sum()),
                 "ties": int((d == 0).sum()), "mean_a": a.mean(), "mean_b": b.mean(), "mean_diff": d.mean(),
                 "ci_lo": lo, "ci_hi": hi, "p": p})
S = list(csv.DictReader(open(RES / "seeds100.csv")))
col = lambda s, m: [float(r[m]) for r in S if r["scheme"] == s]
for o in ("RepStake", "PoMonitor"):
    for m in ("infiltration_pct", "proposer_capture_pct"):
        test("seeds100", f"PoET2S vs {o}", m, col("PoET2S", m), col(o, m))
B = list(csv.DictReader(open(RES / "byzantine_sweep.csv")))
for f in sorted({r["fraction"] for r in B}, key=float):
    for o in ("PoMonitor", "RepStake"):
        g = lambda s: [float(r["safety_violation_pct"]) for r in sorted(B, key=lambda r: int(r["seed"])) if r["fraction"] == f and r["scheme"] == s]
        test("byzantine_safety", f"PoET2S vs {o} @ {f}", "safety_violation_pct", g("PoET2S"), g(o))
ps = np.array([r["p"] for r in rows]); order = np.argsort(ps); m = len(ps); holm = np.empty(m); run = 0
for rank, i in enumerate(order):
    run = max(run, min(1.0, (m - rank) * ps[i])); holm[i] = run
for r, h in zip(rows, holm): r["p_holm"] = h
with open(RES / "stats_v19.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader()
    for r in rows: w.writerow({k: (float(f"{v:.6g}") if isinstance(v, (float, np.floating)) else v) for k, v in r.items()})
for r in rows:
    print(f"{r['comparison']:28s} {r['metric']:22s} wins {r['wins']:3d}/{r['n']} ties {r['ties']:3d} "
          f"{r['mean_a']:.2f} vs {r['mean_b']:.2f} diff {r['mean_diff']:+.2f} [{r['ci_lo']:+.2f},{r['ci_hi']:+.2f}] p={r['p']:.2g} holm={r['p_holm']:.2g}")
