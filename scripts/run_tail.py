"""Per-block latency tail (p95, p99) for PoET2S three-phase vs fast path, N=500, 15%, 30 seeds."""
import csv, sys, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from poet2s_sim.detection import run_protocol_slots
RES = Path(__file__).resolve().parent.parent / "results"
rows=[]
for tag, kw in [("PoET2S", None), ("PoET2S-fast", {"commit_mode": "fast"})]:
    lat=[]
    for seed in range(42,72):
        r = run_protocol_slots("PoET2S", n_nodes=500, seed=seed, n_slots=60, malicious_ratio=0.15, proto_kwargs=kw)
        lat += [x.latency_ms for x in r]
    p95,p99=np.percentile(lat,[95,99]); rows.append({"scheme":tag,"n_blocks":len(lat),"mean":np.mean(lat),"p95":p95,"p99":p99})
    print(rows[-1], flush=True)
with open(RES/"latency_tail.csv","w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
