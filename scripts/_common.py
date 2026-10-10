"""Shared helpers for the v19 robustness scripts."""
import statistics as st
from poet2s_sim.detection import run_protocol_slots

N, SLOTS = 500, 60
SAFETY_PCT = 100.0 / 3 - 1e-9   # malicious share >= 1/3 of the validating set


def run(scheme, seed, frac=0.15, **kw):
    r = run_protocol_slots(scheme, n_nodes=N, seed=seed, n_slots=SLOTS, malicious_ratio=frac,
                           proto_kwargs=kw or None)
    n_mal = int(N * frac)
    caught = r[-1].attackers_caught
    assert all(x.committed for x in r), (scheme, seed, "block not committed within the slot window")
    return {
        "caught_pct": 100.0 * caught / n_mal,
        "false_pos": r[-1].false_pos_cum,
        "fp_per_caught": r[-1].false_pos_cum / max(caught, 1),
        "infiltration_pct": st.mean(x.infiltration_pct for x in r),
        "proposer_capture_pct": 100.0 * st.mean(1.0 if x.proposer_malicious else 0.0 for x in r),
        "safety_violation_pct": 100.0 * st.mean(1.0 if x.infiltration_pct >= SAFETY_PCT else 0.0 for x in r),
        "max_malicious_share": max(x.infiltration_pct for x in r),
        "latency_ms": st.mean(x.latency_ms for x in r),
        "first_commit_ms": st.mean(x.first_commit_ms for x in r if x.first_commit_ms is not None),
        "fast_path_pct": (100.0 * st.mean(1.0 if x.fast_path else 0.0 for x in r)
                          if r[0].fast_path is not None else float("nan")),
        # share of blocks whose committee holds more than f = 4 Byzantine members, i.e. more
        # than the two-step path tolerates (5 or more of 21)
        "fast_risk_pct": 100.0 * st.mean(1.0 if x.infiltration_pct >= 500.0 / 21 - 1e-9 else 0.0 for x in r),
    }
