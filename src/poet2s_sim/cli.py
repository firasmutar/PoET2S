"""Command-line interface for one-off protocol runs.

Examples
--------
    poet2s-run PoET2S --nodes 500 --slots 60 --seed 42
    poet2s-run PBFT --nodes 200 --slots 30 --seed 7
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

from poet2s_sim.detection import run_protocol_slots
from poet2s_sim.protocols import CONSENSUS_CLASSES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="poet2s-run",
        description="Run one consensus protocol for N slots and report measurements.",
    )
    parser.add_argument(
        "scheme",
        choices=sorted(CONSENSUS_CLASSES.keys()),
        help="Consensus protocol to run.",
    )
    parser.add_argument("--nodes", type=int, default=500, help="Network size N (default 500).")
    parser.add_argument("--slots", type=int, default=60, help="Slots per run (default 60).")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default 42).")
    parser.add_argument(
        "--tx-per-slot", type=int, default=120, help="Transactions per slot (default 120)."
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=150,
        help="Per-slot detection sample size (default 150).",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Optional path to write per-slot results as CSV.",
    )
    args = parser.parse_args(argv)

    print(
        f"Running {args.scheme} at N={args.nodes}, seed={args.seed}, "
        f"{args.slots} slots, {args.tx_per_slot} tx/slot ..."
    )
    results = run_protocol_slots(
        args.scheme,
        n_nodes=args.nodes,
        seed=args.seed,
        n_slots=args.slots,
        tx_per_slot=args.tx_per_slot,
        detect_sample_size=args.sample_size,
    )

    lat = np.mean([r.latency_ms for r in results])
    tps = np.mean([r.throughput_tps for r in results])
    msgs = np.mean([r.msgs_sent for r in results])
    caught = results[-1].attackers_caught
    n_mal = int(args.nodes * 0.15)
    fps = results[-1].false_pos_cum
    oh = np.mean([r.wall_clock_ms for r in results])

    print(f"\n== {args.scheme} summary ==")
    print(f"  mean latency      : {lat:.1f} ms")
    print(f"  commit capacity   : {tps:.1f} tx/s (block size / latency; not a sustained rate, not used in the paper)")
    print(f"  mean msgs/block   : {msgs:.0f}")
    print(f"  attackers caught  : {caught}/{n_mal} ({100*caught/max(n_mal,1):.1f}%)")
    print(f"  total FPs         : {fps}")
    print(f"  FP per caught     : {fps/max(caught,1):.2f}")
    print(f"  wall-clock/slot   : {oh:.1f} ms")

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with open(args.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "slot",
                    "proposer",
                    "latency_ms",
                    "msgs_sent",
                    "throughput_tps",
                    "attackers_caught",
                    "false_pos_this_slot",
                    "false_pos_cum",
                    "wall_clock_ms",
                ]
            )
            for r in results:
                w.writerow(
                    [
                        r.slot,
                        r.proposer,
                        r.latency_ms,
                        r.msgs_sent,
                        r.throughput_tps,
                        r.attackers_caught,
                        r.false_pos_this_slot,
                        r.false_pos_cum,
                        r.wall_clock_ms,
                    ]
                )
        print(f"\n  per-slot CSV -> {args.csv}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
