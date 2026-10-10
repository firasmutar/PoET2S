"""Identity-splitting (Sybil) experiment (v18).

An attacker controls a fixed budget B of total network stake and the same
share of total PV capacity, B in {1%, 2%, 5%}. It splits the budget evenly across m identities, each held
at trust TTS_s. After 60 slots of normal operation (so honest trust and
energy terms are at steady state), the committee is the top-K = 21 nodes by
eq. (4). We record how many committee seats the attacker's identities win.

Compared: PoET2S (gamma = 2.5) and the linear design point (gamma = 1).
Writes results/sybil.csv.
"""
from __future__ import annotations

import csv
import random
import statistics as st
import sys
from pathlib import Path

import numpy as np

from poet2s_sim.grid_model import DigitalTwin, GridNode, apply_attacks, build_grid, sample_slot

N, K, SLOTS = 500, 21, 60
SEEDS = list(range(42, 52))
SPLITS = [1, 2, 5, 10, 20, 50]
TRUSTS = [1.0, 0.8, 0.6, 0.4]
BUDGETS = [0.01, 0.02, 0.05]
GAMMAS = {"PoET2S (gamma=2.5)": 2.5, "linear (gamma=1)": 1.0}
W_S, W_E, ETA = 0.35, 0.45, 0.22
OUT = Path(__file__).resolve().parent.parent / "results" / "sybil.csv"


def steady_state(seed):
    rng = random.Random(seed)
    nodes = build_grid(N, 0.15, rng)
    np_rng = np.random.default_rng(seed)
    twin = DigitalTwin()
    for t in range(SLOTS):
        twin.tick()
        sample_slot(nodes, t, np_rng)
        for n in nodes:
            twin.forecast(n)
        apply_attacks(nodes, np_rng, twin)
        for n in nodes:
            a = twin.verify(n)
            twin.record(n)
            twin.update_energy(n)
            n.trust_score = float(np.clip((1 - ETA) * n.trust_score + ETA * (1 - a), 0.01, 1.0))
    return nodes


def main() -> int:
    rows, tts_rows = [], []
    for seed in SEEDS:
        nodes = steady_state(seed)
        s_bar = st.mean(n.stake for n in nodes)
        honest_tts = [n.trust_score for n in nodes if n.honest]
        tts_rows.append({"seed": seed, "honest_tts_mean": st.mean(honest_tts),
                         "honest_tts_q1": float(np.percentile(honest_tts, 25)),
                         "honest_tts_q3": float(np.percentile(honest_tts, 75))})
        prod = [n for n in nodes if n.role != "consumer"]
        # energy term per unit capacity at steady state (honest producers)
        e_per_kw = st.mean(n.energy_contribution / n.capacity_kwh for n in prod
                           if n.honest and n.capacity_kwh > 0)
        for budget in BUDGETS:
          stake_budget = budget * sum(n.stake for n in nodes)
          cap_budget = budget * sum(n.capacity_kwh for n in nodes)
          for gname, g in GAMMAS.items():
              honest_w = sorted(((W_S * n.stake / s_bar + W_E * (n.energy_contribution + 1))
                                 * n.trust_score ** g for n in nodes), reverse=True)
              for m in SPLITS:
                  for tts in TRUSTS:
                      e_id = e_per_kw * cap_budget / m
                      w_id = (W_S * (stake_budget / m) / s_bar + W_E * (e_id + 1)) * tts ** g
                      pool = honest_w[:K] + [w_id] * m
                      top = sorted(pool, reverse=True)[:K]
                      # seats won = identities among the top K (ties go to honest)
                      seats = sum(1 for w in top if w == w_id) if w_id > top[-1] or m <= 0 else \
                          sum(1 for w in top if w == w_id)
                      rows.append({"seed": seed, "budget_pct": int(budget * 100), "scheme": gname, "identities": m,
                                   "tts_sybil": tts, "seats": seats,
                                   "share_pct": round(100 * seats / K, 2),
                                   "identity_weight": round(w_id, 4),
                                   "kth_honest_weight": round(honest_w[K - 1], 4)})
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(OUT.with_name("sybil_honest_tts.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(tts_rows[0]))
        w.writeheader()
        w.writerows(tts_rows)
    print("honest steady-state TTS: mean %.3f, IQR %.3f-%.3f" % (
        st.mean(r["honest_tts_mean"] for r in tts_rows),
        st.mean(r["honest_tts_q1"] for r in tts_rows), st.mean(r["honest_tts_q3"] for r in tts_rows)))
    for budget in BUDGETS:
      for gname in GAMMAS:
        print(f"budget {int(budget*100)}%  {gname}")
        for tts in TRUSTS:
            line = " ".join(f"m={m}:{st.mean(r['seats'] for r in rows if r['budget_pct']==int(budget*100) and r['scheme']==gname and r['identities']==m and r['tts_sybil']==tts):4.1f}"
                            for m in SPLITS)
            print(f"  TTS_s={tts}: {line}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
