"""Hardened variants, 30 seeds (v19). Writes results/hardened.csv.
  -H  : base weight without the per-identity constant (energy_offset = 0), top-K committee
  -HS : energy_offset = 0 and committee drawn by weighted sortition (probability ~ weight)
"""
import csv, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import run
SEEDS = range(42, 72)
OUT = Path(__file__).resolve().parent.parent / "results" / "hardened.csv"
CFG = [("PoET2S", "-H", {"energy_offset": 0.0}),
       ("PoET2S", "-HS", {"energy_offset": 0.0, "committee_mode": "sortition"}),
       ("RepStake", "-HS", {"energy_offset": 0.0, "committee_mode": "sortition"}),
       ("PoMonitor", "-HS", {"energy_offset": 0.0, "committee_mode": "sortition"})]
rows = []
for scheme, tag, kw in CFG:
    for seed in SEEDS:
        rows.append({"scheme": scheme + tag, "seed": seed, **run(scheme, seed, **kw)})
    print(scheme + tag, "done", flush=True)
with open(OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print("wrote", OUT)
