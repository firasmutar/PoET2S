"""PoET2S vs the linear rule on 100 seeds (42-141). Writes results/seeds100.csv."""
import csv, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import run
OUT = Path(__file__).resolve().parent.parent / "results" / "seeds100.csv"
rows = []
for scheme in ["PoET2S", "RepStake", "PoMonitor"]:
    for seed in range(42, 142):
        rows.append({"scheme": scheme, "seed": seed, **run(scheme, seed)})
    print(scheme, flush=True)
with open(OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print("wrote", OUT)
