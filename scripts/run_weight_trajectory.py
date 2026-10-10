"""Selection weight of one node versus lie magnitude over time (v18).

One prosumer (6.5 kW PV, 1.3 kW mean load, median stake) runs for 72 slots.
From slot 12 onward it reports its generation multiplied by a constant factor
m (m = 1 is honest). We track TTS (eq. 3), the verified energy term e (eq. 4)
and the resulting selection weight under three rules: the veto (weight kept
until the instantaneous anomaly exceeds 0.5, then zero for that slot), the
linear rule (gamma = 1) and PoET2S (gamma = 2.5). Weights are divided by the
same node's weight when honest. Writes results/weight_trajectory.csv.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

from poet2s_sim.grid_model import DigitalTwin, GridNode, pecan_umass_sample

SLOTS, LIE_START = 72, 12
LIES = [1.0, 1.1, 1.25, 1.5, 2.0]
W_S, W_E, ETA, S_REL = 0.35, 0.45, 0.22, 1.0      # stake at the network mean
OUT = Path(__file__).resolve().parent.parent / "results" / "weight_trajectory.csv"


def trace(m: float, seed: int = 5):
    np_rng = np.random.default_rng(seed)
    node = GridNode(node_id=0, role="prosumer", capacity_kwh=6.5, demand_kwh=1.3, stake=1.0)
    twin = DigitalTwin()
    out = []
    for t in range(SLOTS):
        twin.tick()
        node.actual_generation, node.actual_demand = pecan_umass_sample(node, t, np_rng)
        twin.forecast(node)
        mult = m if t >= LIE_START else 1.0
        node.reported_generation = node.actual_generation * mult
        node.reported_demand = node.actual_demand
        a = twin.verify(node)
        twin.record(node)
        twin.update_energy(node)
        node.trust_score = float(np.clip((1 - ETA) * node.trust_score + ETA * (1 - a), 0.01, 1.0))
        base = W_S * S_REL + W_E * (node.energy_contribution + 1.0)
        out.append({"slot": t, "anomaly": a, "tts": node.trust_score,
                    "energy": node.energy_contribution,
                    "w_veto": 0.0 if a > 0.5 else base,
                    "w_linear": base * node.trust_score,
                    "w_poet2s": base * node.trust_score ** 2.5})
    return out


def main() -> int:
    honest = trace(1.0)
    rows = []
    for m in LIES:
        for h, r in zip(honest, trace(m)):
            rows.append({"lie": m, "slot": r["slot"], "anomaly": round(r["anomaly"], 4),
                         "tts": round(r["tts"], 4), "energy": round(r["energy"], 4),
                         "energy_rel": round(r["energy"] / h["energy"], 4) if h["energy"] > 0 else 1.0,
                         "veto_rel": round(r["w_veto"] / h["w_veto"], 4) if h["w_veto"] > 0 else 0.0,
                         "linear_rel": round(r["w_linear"] / h["w_linear"], 4),
                         "poet2s_rel": round(r["w_poet2s"] / h["w_poet2s"], 4)})
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for m in LIES:
        sub = [r for r in rows if r["lie"] == m and r["slot"] >= 36]
        print(f"lie x{m}: mean relative weight (slots 36-71)  veto={np.mean([r['veto_rel'] for r in sub]):.2f} "
              f"linear={np.mean([r['linear_rel'] for r in sub]):.2f} poet2s={np.mean([r['poet2s_rel'] for r in sub]):.2f} "
              f"energy={np.mean([r['energy_rel'] for r in sub]):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
