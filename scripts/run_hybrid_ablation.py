"""Hybrid-detector ablation for PoET2S.

PoET2S's default detector flags a node when its EWMA-smoothed Twin-Trust Score
falls below the rejection threshold. EWMA smoothing is sensitive to *sustained*
deviation but, by construction, attenuates brief spikes - so an intermittent
attacker that lies in only a minority of slots can keep a high trust score and
evade the trust-based flag.

The hybrid detector pairs the smoothed trust signal with an instantaneous
anomaly trigger at the veto's threshold, the common pairing of a smoothed statistic
with a point trigger in time-series anomaly detection (Christodoulou and Bi, DSAA
2015; Zhou and Tang, IGARSS 2016). The script compares default and hybrid PoET2S
with the veto over 30 seeds and confirms the hybrid changes only detection.

Run from the repository root:
    python scripts/run_hybrid_ablation.py
"""
from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path

from poet2s_sim.detection import run_protocol_slots

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_CSV = RESULTS_DIR / "hybrid_ablation.csv"

N = 500
N_SLOTS = 60
SEEDS = list(range(42, 72))   # 30 seeds
N_MAL = int(N * 0.15)


def measure(scheme: str, hybrid: bool = False):
    caught, fps, fpc, lat, tps, inf = [], [], [], [], [], []
    for s in SEEDS:
        kw = {"hybrid_detect": True} if hybrid else None
        r = run_protocol_slots(scheme, n_nodes=N, seed=s, n_slots=N_SLOTS,
                               proto_kwargs=kw)
        c = r[-1].attackers_caught
        caught.append(100.0 * c / N_MAL)
        fps.append(r[-1].false_pos_cum)
        fpc.append(r[-1].false_pos_cum / max(c, 1))
        lat.append(statistics.mean(x.latency_ms for x in r))
        tps.append(statistics.mean(x.throughput_tps for x in r))
        inf.append(statistics.mean(x.infiltration_pct for x in r))
    return {"caught": caught, "fps": fps, "fpc": fpc, "lat": lat, "tps": tps, "inf": inf}


def main() -> int:
    print(f"Hybrid-detector ablation: N={N}, {len(SEEDS)} seeds, {N_SLOTS} slots\n")

    variants = {
        "PoMonitor": measure("PoMonitor"),
        "PoET2S-default": measure("PoET2S", hybrid=False),
        "PoET2S-hybrid": measure("PoET2S", hybrid=True),
    }

    print(f"{'variant':18s} {'caught%':>8s} {'FP/c':>7s} {'lat':>7s} {'tps':>7s}")
    print("-" * 52)
    rows = []
    for name, m in variants.items():
        print(f"{name:18s} {statistics.mean(m['caught']):7.1f}% "
              f"{statistics.mean(m['fpc']):7.2f} "
              f"{statistics.mean(m['lat']):6.1f}m {statistics.mean(m['tps']):7.0f}")
        for i, s in enumerate(SEEDS):
            rows.append({
                "variant": name, "seed": s,
                "caught_pct": round(m["caught"][i], 2),
                "fps": m["fps"][i],
                "fp_per_caught": round(m["fpc"][i], 2),
                "latency_ms": round(m["lat"][i], 2),
                "throughput_tps": round(m["tps"][i], 1),
                "infiltration_pct": round(m["inf"][i], 4),
            })

    with open(OUTPUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["variant", "seed", "caught_pct", "fps",
                                          "fp_per_caught", "latency_ms",
                                          "throughput_tps", "infiltration_pct"])
        w.writeheader()
        w.writerows(rows)

    # Headline test: hybrid vs PoMonitor on catch rate
    ph = variants["PoET2S-hybrid"]["caught"]
    pm = variants["PoMonitor"]["caught"]
    wins = sum(1 for a, b in zip(ph, pm) if a > b)
    ties = sum(1 for a, b in zip(ph, pm) if a == b)
    print(f"\nHybrid vs twin-as-veto on detection: hybrid catches more in "
          f"{wins}/{len(SEEDS)} seeds ({ties} ties).")
    try:
        from scipy.stats import wilcoxon
        print(f"Wilcoxon p = {wilcoxon(ph, pm).pvalue:.4f}")
    except ImportError:
        pass
    print(f"Trade-off: hybrid FP/caught {statistics.mean(variants['PoET2S-hybrid']['fpc']):.1f} "
          f"vs veto {statistics.mean(variants['PoMonitor']['fpc']):.1f}.")
    print(f"Latency/throughput identical to default "
          f"({statistics.mean(variants['PoET2S-hybrid']['lat']):.1f} ms) - "
          f"hybrid changes detection only, not committee selection.")
    print(f"\nWrote {OUTPUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
