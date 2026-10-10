"""Two-step fast-path commit (v20). Part A: N = 500, 15% Byzantine, 30 seeds, fast-path variants of the
committee schemes plus first-commit latency of the classical schemes and default PoET2S.
Part B (argument 'sweep'): Byzantine-fraction sweep for PoET2S and the veto with the fast path.
Writes results/fastpath_main.csv or results/fastpath_sweep.csv."""
import csv, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import run
RES = Path(__file__).resolve().parent.parent / "results"
SEEDS = range(42, 72)
rows = []
if len(sys.argv) > 1 and sys.argv[1] == "sweep":
    for frac in (0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45):
        for scheme in ("PoET2S", "PoMonitor"):
            for seed in SEEDS:
                rows.append({"fraction": frac, "scheme": scheme + "-fast", "seed": seed,
                             **run(scheme, seed, frac, commit_mode="fast")})
            print(frac, scheme, flush=True)
    out = RES / "fastpath_sweep.csv"
else:
    for scheme, kw, tag in [("PoET2S", {"commit_mode": "fast"}, "-fast"), ("PoMonitor", {"commit_mode": "fast"}, "-fast"),
                            ("RepStake", {"commit_mode": "fast"}, "-fast"), ("PoET2S", {}, ""), ("PoET2S", {"byz_withhold": True}, "-withhold"),
                            ("PoMonitor", {"byz_withhold": True}, "-withhold"), ("PoS", {}, ""),
                            ("DPoS", {}, ""), ("PBFT", {}, "")]:
        for seed in SEEDS:
            rows.append({"scheme": scheme + tag, "seed": seed, **run(scheme, seed, **kw)})
        print(scheme + tag, flush=True)
    out = RES / "fastpath_main.csv"
with open(out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print("wrote", out)
