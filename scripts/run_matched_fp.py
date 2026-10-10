"""Operating-point sweep (v19): vary each twin-based scheme's detection/eligibility threshold
and record (FP per catch, caught, infiltration), 30 seeds. Used to compare infiltration at
matched false-positive cost. Writes results/matched_fp.csv."""
import csv, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import run
SEEDS = range(42, 72)
CONFIGS = ([("PoMonitor", "veto_threshold", v) for v in (0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70)]
           + [("EACM", "trust_floor", v) for v in (0.30, 0.40, 0.50, 0.60, 0.70)]
           + [("PoET2S", "tts_reject", v) for v in (0.20, 0.30, 0.35, 0.45, 0.60)]
           + [("PoET2S", "eta", v) for v in (0.05, 0.10, 0.40)]
           + [("RepStake", "eta", v) for v in (0.05, 0.10, 0.40)])
OUT = Path(__file__).resolve().parent.parent / "results" / "matched_fp.csv"
rows = []
for scheme, par, val in CONFIGS:
    for seed in SEEDS:
        rows.append({"scheme": scheme, "param": par, "value": val, "seed": seed, **run(scheme, seed, **{par: val})})
    print(scheme, par, val, flush=True)
with open(OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print("wrote", OUT)
