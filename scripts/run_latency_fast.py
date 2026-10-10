"""Latency breakdown for the two-step fast path (v20), same conditions and seeds as
run_latency_accounting.py. Writes results/latency_fast.csv."""
import csv, statistics as st, sys
from pathlib import Path
import poet2s_sim.protocols as P
from poet2s_sim.detection import run_protocol_slots
sys.path.insert(0, str(Path(__file__).parent))
from run_latency_accounting import CONDITIONS, SEEDS, SLOTS
RES = Path(__file__).resolve().parent.parent / "results"
rows = []
def measure(n, nk, ck, body=None):
    seeds, slots = (SEEDS, SLOTS) if n <= 500 else (SEEDS[:3], 5)
    saved = {k: getattr(P, k) for k in ck}; old = P.PROPOSAL_BYTES
    for k, v in ck.items(): setattr(P, k, v)
    if body: P.PROPOSAL_BYTES = body
    try:
        lat = []
        for s in seeds:
            lat += [x.latency_ms for x in run_protocol_slots("PoET2S", n_nodes=n, seed=s, n_slots=slots,
                    net_kwargs=nk, proto_kwargs={"commit_mode": "fast"})]
        return st.mean(lat)
    finally:
        for k, v in saved.items(): setattr(P, k, v)
        P.PROPOSAL_BYTES = old
for n in (500, 2000):
    for cond, (nk, ck) in CONDITIONS.items():
        rows.append({"N": n, "condition": cond, "latency_ms": round(measure(n, nk, ck), 3)}); print(rows[-1], flush=True)
rows.append({"N": 500, "condition": "full_body", "latency_ms": round(measure(500, {}, {}, 256 + P.TX_PER_BLOCK * P.TX_BYTES), 3)})
print(rows[-1])
with open(RES / "latency_fast.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
