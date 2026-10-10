"""Expected Sybil seats when the committee is drawn by weighted sortition (v19).
Offset 0 (no per-identity constant), gamma = 2.5, 5% budget, 10 seeds, 400 draws per case.
Writes results/sybil_sortition.csv."""
import csv, statistics as st, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
from run_sybil import steady_state, K, SEEDS, W_S, W_E
OUT = Path(__file__).resolve().parent.parent / "results" / "sybil_sortition.csv"
rows = []
for seed in SEEDS:
    nodes = steady_state(seed)
    s_bar = st.mean(n.stake for n in nodes)
    honest = [n for n in nodes if n.honest]
    med = float(np.median([n.trust_score for n in honest]))
    e_per_kw = st.mean(n.energy_contribution / n.capacity_kwh for n in honest if n.capacity_kwh > 0)
    hw = np.array([(W_S * n.stake / s_bar + W_E * n.energy_contribution) * n.trust_score ** 2.5 for n in nodes])
    sb = 0.05 * sum(n.stake for n in nodes); cb = 0.05 * sum(n.capacity_kwh for n in nodes)
    rng = np.random.default_rng(seed)
    for m in (1, 2, 5, 10, 20, 50):
        for entry in ("1.0", "honest"):
            tts = med if entry == "honest" else 1.0
            w_id = (W_S * (sb / m) / s_bar + W_E * (e_per_kw * cb / m)) * tts ** 2.5
            w = np.concatenate([hw, np.full(m, w_id)]); p = w / w.sum()
            seats = [np.sum(rng.choice(len(w), K, replace=False, p=p) >= len(hw)) for _ in range(400)]
            rows.append({"seed": seed, "identities": m, "entry_tts": entry, "mean_seats": float(np.mean(seats)),
                         "p_ge7": float(np.mean(np.array(seats) >= 7)), "weight_share": float(m * w_id / w.sum())})
with open(OUT, "w", newline="") as f:
    wr = csv.DictWriter(f, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
for entry in ("1.0", "honest"):
    print(entry, " ".join(f"m={m}:{st.mean(r['mean_seats'] for r in rows if r['identities']==m and r['entry_tts']==entry):.2f}/p7={st.mean(r['p_ge7'] for r in rows if r['identities']==m and r['entry_tts']==entry):.3f}" for m in (1,2,5,10,20,50)))
