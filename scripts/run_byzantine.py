"""Byzantine-fraction sweep (v19): 10%-45% malicious, four twin-based schemes, 30 seeds.
Adds the safety-violation rate: share of blocks whose validating committee is at least
one-third Byzantine. Writes results/byzantine_sweep.csv."""
import csv, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import run
SEEDS = range(42, 72)
FRACTIONS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45]
SCHEMES = ["PoMonitor", "EACM", "RepStake", "PoET2S"]
OUT = Path(__file__).resolve().parent.parent / "results" / "byzantine_sweep.csv"
rows = []
for frac in FRACTIONS:
    for scheme in SCHEMES:
        for seed in SEEDS:
            rows.append({"fraction": frac, "scheme": scheme, "seed": seed, **run(scheme, seed, frac)})
        print(frac, scheme, flush=True)
with open(OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print("wrote", OUT)
