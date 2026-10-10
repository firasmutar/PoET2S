"""Latency and throughput accounting (v18), answering three questions:

 (i)   block size and transactions per block behind the throughput figure;
 (ii)  where commit latency goes: phase timings, plus counterfactual runs that
       remove one component at a time (cryptography, bandwidth/queueing,
       propagation);
 (iii) why PBFT latency grows with N while the committee schemes stay flat.

Also re-runs the four consensus families with full block bodies in the
proposal (120 tx x 250 B) instead of a 1 KB header.
Writes results/latency_breakdown.csv, results/latency_payload.csv.
"""
from __future__ import annotations

import csv
import statistics as st
import sys
from pathlib import Path

import poet2s_sim.protocols as P
from poet2s_sim.detection import run_protocol_slots

RES = Path(__file__).resolve().parent.parent / "results"
SEEDS = [42, 43, 44, 45, 46]
SLOTS = 20
SCHEMES = ["PoS", "DPoS", "PBFT", "PoET2S"]

CONDITIONS = {
    "full": ({}, {}),
    "no_crypto": ({"processing_ms": 0.0}, {"SIGN_MS": 0.0, "COMPUTE_MS_PER_MSG": 0.0}),
    "no_queueing": ({"bandwidth_mbps": 1e9}, {}),
    "no_propagation": ({"rtt_min_ms": 0.0}, {}),
}


def measure(scheme, n, net_kw, const_kw):
    seeds, slots = (SEEDS, SLOTS) if n <= 500 else (SEEDS[:3], 5)
    saved = {k: getattr(P, k) for k in const_kw}
    for k, v in const_kw.items():
        setattr(P, k, v)
    try:
        lat, tp, tq = [], [], []
        for seed in seeds:
            r = run_protocol_slots(scheme, n_nodes=n, seed=seed, n_slots=slots,
                                   net_kwargs=net_kw)
            lat += [x.latency_ms for x in r]
            tp += [x.t_q_proposal for x in r if x.t_q_proposal is not None]
            tq += [x.t_q_prepared for x in r if x.t_q_prepared is not None]
        return (st.mean(lat), st.mean(tp) if tp else float("nan"),
                st.mean(tq) if tq else float("nan"))
    finally:
        for k, v in saved.items():
            setattr(P, k, v)


def main() -> int:
    rows = []
    for n, schemes in ((500, SCHEMES), (2000, ["PBFT", "PoET2S"])):
        for scheme in schemes:
            for cond, (nk, ck) in CONDITIONS.items():
                lat, tp, tq = measure(scheme, n, nk, ck)
                rows.append({"N": n, "scheme": scheme, "condition": cond,
                             "latency_ms": round(lat, 3),
                             "t_q_proposal_ms": round(tp, 3),
                             "t_q_prepared_ms": round(tq, 3)})
                print(f"  N={n} {scheme:6s} {cond:15s} lat={lat:7.2f} "
                      f"proposal_q={tp:6.2f} prepared_q={tq:6.2f}", flush=True)
    with open(RES / "latency_breakdown.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    # full block bodies in the proposal
    prow = []
    full_body = 256 + P.TX_PER_BLOCK * P.TX_BYTES
    for size, label in ((1024, "header_1KB"), (full_body, "full_body")):
        P.PROPOSAL_BYTES = size
        for scheme in SCHEMES:
            lat, _, _ = measure(scheme, 500, {}, {})
            prow.append({"proposal": label, "proposal_bytes": size, "scheme": scheme,
                         "latency_ms": round(lat, 3)})
            print(f"  payload {label:10s} {scheme:6s} lat={lat:7.2f}", flush=True)
    P.PROPOSAL_BYTES = 1024
    with open(RES / "latency_payload.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(prow[0]))
        w.writeheader()
        w.writerows(prow)
    print("wrote latency_breakdown.csv, latency_payload.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
