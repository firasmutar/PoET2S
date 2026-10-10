"""Sybil identity splitting under the hardening measures (v19).

Same set-up as run_sybil.py (steady state after 60 slots, top-K = 21 by eq. 4, 10 seeds).
Variants:
  offset 1 / 0   : base weight with / without the per-identity constant w_e
  entry trust    : 1.0 (no ramp), 0.4 (newcomer ramp start), 'honest' (after probation,
                   the identity has the per-seed median honest TTS)
  bond           : an identity must hold at least the 10th percentile of honest stake;
                   splits that violate the bond are infeasible (seats reported as blank)
Writes results/sybil_hardening.csv.
"""
import csv, random, statistics as st, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
from run_sybil import steady_state, N, K, SEEDS, W_S, W_E  # noqa: E402

SPLITS = [1, 2, 5, 10, 20, 50]
BUDGETS = [0.01, 0.02, 0.05]
GAMMAS = {"PoET2S": 2.5, "linear": 1.0}
OUT = Path(__file__).resolve().parent.parent / "results" / "sybil_hardening.csv"


def main():
    rows = []
    for seed in SEEDS:
        nodes = steady_state(seed)
        s_bar = st.mean(n.stake for n in nodes)
        honest = [n for n in nodes if n.honest]
        tts_med = float(np.median([n.trust_score for n in honest]))
        bond = float(np.percentile([n.stake for n in honest], 10))
        prod = [n for n in honest if n.capacity_kwh > 0]
        e_per_kw = st.mean(n.energy_contribution / n.capacity_kwh for n in prod)
        for off in (1.0, 0.0):
            for gname, g in GAMMAS.items():
                hw = sorted(((W_S * n.stake / s_bar + W_E * (n.energy_contribution + off)) * n.trust_score ** g
                             for n in nodes), reverse=True)
                for budget in BUDGETS:
                    sb = budget * sum(n.stake for n in nodes)
                    cb = budget * sum(n.capacity_kwh for n in nodes)
                    for m in SPLITS:
                        for entry in ("1.0", "0.4", "honest"):
                            tts = tts_med if entry == "honest" else float(entry)
                            w_id = (W_S * (sb / m) / s_bar + W_E * (e_per_kw * cb / m + off)) * tts ** g
                            top = sorted(hw[:K] + [w_id] * m, reverse=True)[:K]
                            seats = sum(1 for w in top if w == w_id)
                            rows.append({"seed": seed, "offset": off, "scheme": gname, "budget_pct": int(budget * 100),
                                         "identities": m, "entry_tts": entry, "seats": seats,
                                         "bond_ok": int(sb / m >= bond)})
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    for off in (1.0, 0.0):
        for gname in GAMMAS:
            for entry in ("1.0", "0.4", "honest"):
                line = " ".join(
                    f"m={m}:{st.mean(r['seats'] for r in rows if r['offset']==off and r['scheme']==gname and r['budget_pct']==5 and r['identities']==m and r['entry_tts']==entry):4.1f}"
                    f"{'' if all(r['bond_ok'] for r in rows if r['budget_pct']==5 and r['identities']==m) else '*'}"
                    for m in SPLITS)
                print(f"5% off={off} {gname:6s} entry={entry:6s} {line}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
