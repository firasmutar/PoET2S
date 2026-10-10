"""
Slot harness (v18). One run produces every per-slot metric in the paper.

Per slot:
  1. twin.tick(), sample_slot() (physics), twin.forecast() for every node
  2. apply_attacks() (adversarial reports)
  3. for every node: twin.record(), twin.update_energy() (eq. 4), and for the
     trust-weighted schemes update_trust() (eq. 3)
  4. detectors are evaluated on a 150-node audit sample drawn with the seed's
     own RNG, so every scheme audits the same nodes in the same slot
  5. propose_block() and run the event loop until the block is final

Measures per slot:
  - latency_ms: block commit time - block start time (per-replica quorums)
  - t_q_proposal / t_q_prepared: phase timestamps for the latency breakdown
  - infiltration_pct: malicious share of the block's validating set
  - proposer_malicious, profit (energy over-reported by malicious members of
    the validating set)
  - attackers_caught (cumulative unique), false_pos_cum (cumulative honest
    node-slot flags)
  - msgs_sent, wall_clock_ms
Throughput is not reported as a separate metric: with one block of
TX_PER_BLOCK transactions per 12 s slot, sustained throughput is
TX_PER_BLOCK / 12 s for every scheme that finalises inside the slot, and the
"commit capacity" TX_PER_BLOCK / latency is only latency rescaled.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

import numpy as np

from poet2s_sim.grid_model import DigitalTwin, GridNode, apply_attacks, build_grid, sample_slot
from poet2s_sim.protocols import (
    CONSENSUS_CLASSES,
    PoET2S,
)
from poet2s_sim.sim_core import DEScheduler, Network


@dataclass
class SlotResult:
    slot: int
    proposer: int
    latency_ms: float
    msgs_sent: int
    throughput_tps: float
    attackers_caught: int      # cumulative
    false_pos_this_slot: int
    false_pos_cum: int
    wall_clock_ms: float
    infiltration_pct: float = 0.0
    proposer_malicious: bool = False
    profit: float = 0.0
    t_q_proposal: float | None = None
    t_q_prepared: float | None = None
    first_commit_ms: float | None = None
    fast_path: bool | None = None
    committed: bool = True


def _flagged_by_protocol(proto_name: str, node: GridNode,
                          twin: DigitalTwin, peer_median_gen: float,
                          peer_median_dem: float,
                          proto=None, anomaly: float | None = None) -> bool:
    """Mechanistic per-protocol detector. Each protocol applies its
    characteristic check; +Twin variants OR the twin's anomaly score on top.

    For PoET2S, the flag is driven by the node's accumulated Twin-Trust Score
    relative to the protocol's tts_reject threshold, so the trust dynamics
    (gamma, eta) and the rejection threshold all influence detection.
    """
    # Twin anomaly check (used by +Twin variants and PoET2S)
    if anomaly is None:
        anomaly = twin.verify(node)
    twin_flag = anomaly > 0.5

    if proto_name == "PoW":
        # PoW has no content check; never flags anyone
        return False

    if proto_name == "PoET2S":
        # PoET2S flags a node once its accumulated trust falls below the
        # rejection threshold. Falls back to the instantaneous anomaly on the
        # first slot before trust has moved. tts_reject is read from the
        # protocol instance so the parameter sweep is faithful.
        reject = getattr(proto, "tts_reject", 0.35)
        trust_flag = node.trust_score < (1.0 - reject)
        # Optional hybrid detector: add an instantaneous trigger at the same
        # sensitivity the veto competitor uses. This pairs the EWMA-smoothed
        # trust signal (sensitive to sustained deviation) with an instantaneous
        # spike trigger (sensitive to abrupt deviation), following the
        # established CUSUM-EWMA combination in time-series anomaly detection.
        if getattr(proto, "hybrid_detect", False):
            veto = getattr(proto, "veto_threshold", 0.5)
            return trust_flag or anomaly > veto
        # Default detector: trust, plus a high-anomaly backstop.
        return trust_flag or anomaly > (1.0 - reject)

    if proto_name == "EACM":
        # Energy-aware consensus: flags a node below its trust-eligibility floor
        # (the same floor used to gate committee membership), with an anomaly
        # backstop. Linear trust, additive eligibility.
        floor = getattr(proto, "trust_floor", 0.4)
        return node.trust_score < floor or anomaly > 0.6

    if proto_name == "RepStake":
        # Reputation-as-stake: linear reputation, flags on the same trust
        # threshold as PoET2S so the only difference from PoET2S is the
        # selection exponent (gamma=1 here vs 2.5).
        reject = getattr(proto, "tts_reject", 0.35)
        return node.trust_score < (1.0 - reject) or anomaly > (1.0 - reject)

    if proto_name == "PoMonitor":
        # Twin-as-veto competitor: the monitor flags purely on the
        # instantaneous twin score crossing the veto threshold. No accumulated
        # trust state - this is the defining contrast with PoET2S.
        veto = getattr(proto, "veto_threshold", 0.5)
        return anomaly > veto

    # Peer-median comparison: baseline mechanism for PoS/PBFT/DPoS
    if peer_median_gen > 0.1:
        dev_gen = abs(node.reported_generation - peer_median_gen) / max(peer_median_gen, 0.5)
    else:
        dev_gen = abs(node.reported_generation - peer_median_gen)
    if peer_median_dem > 0.1:
        dev_dem = abs(node.reported_demand - peer_median_dem) / max(peer_median_dem, 0.5)
    else:
        dev_dem = abs(node.reported_demand - peer_median_dem)

    if proto_name == "PoS":
        # 60% deviation threshold
        return dev_gen > 0.60 or dev_dem > 0.60
    if proto_name == "PBFT":
        # 40% deviation threshold (validators are stricter)
        return dev_gen > 0.40 or dev_dem > 0.40
    if proto_name == "DPoS":
        # 50% deviation, delegate-median
        return dev_gen > 0.50 or dev_dem > 0.50

    # +Twin variants: protocol detector OR twin anomaly
    base_proto = proto_name.replace("+Twin", "")
    base_flag = _flagged_by_protocol(base_proto, node, twin,
                                      peer_median_gen, peer_median_dem,
                                      anomaly=anomaly)
    return base_flag or twin_flag


def run_protocol_slots(proto_name: str, n_nodes: int, seed: int,
                       n_slots: int = 60, tx_per_slot: int = 120,
                       detect_sample_size: int = 150,
                       adaptive_attacks: bool = False,
                       strategic: bool | str = False,
                       malicious_ratio: float = 0.15,
                       proto_kwargs: dict | None = None,
                       net_kwargs: dict | None = None) -> list[SlotResult]:
    """Run one protocol for n_slots slots and return per-slot results.

    Pairing: the grid, the malicious set, the physical traces, the static
    attack draws and the audit sample depend only on `seed`, so two schemes
    run with the same seed face the same attack realisation. (Adaptive
    attackers react to their own trust score, so under `strategic` the
    realisations diverge by design.)
    """
    cls = CONSENSUS_CLASSES[proto_name]
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    nodes = build_grid(n_nodes, malicious_ratio, rng, adaptive=adaptive_attacks)
    twin = DigitalTwin()
    sched = DEScheduler()
    net_cfg = {"bandwidth_mbps": 50.0, "rtt_min_ms": 10.0}
    net_cfg.update(net_kwargs or {})
    net = Network(sched, n_nodes, rng=random.Random(seed + 1000), **net_cfg)
    proto = cls(sched, net, nodes, twin, rng=random.Random(seed + 2000),
                **(proto_kwargs or {}))
    malicious = {n.node_id for n in nodes if not n.honest}
    trust_weighted = isinstance(proto, PoET2S)

    caught_attackers: set[int] = set()
    false_pos_cum = 0
    results: list[SlotResult] = []

    for slot in range(n_slots):
        wt0 = time.perf_counter()
        msgs_before = net.messages_sent

        # 1. physics and forecasts for every node
        twin.tick()
        sample_slot(nodes, slot, np_rng)
        sample_ids = rng.sample(range(n_nodes), min(detect_sample_size, n_nodes))
        for n in nodes:
            twin.forecast(n)

        # 2. attacks
        apply_attacks(nodes, np_rng, twin, strategic=strategic)

        # 3. twin state for every node (anomaly -> trust, verified energy)
        anomalies = {}
        for n in nodes:
            anomalies[n.node_id] = twin.verify(n)
            twin.record(n)
            twin.update_energy(n)
            if trust_weighted:
                proto.update_trust(n)

        # 4. detection on the audit sample
        sampled_nodes = [nodes[i] for i in sample_ids]
        peer_gen = float(np.median([n.reported_generation for n in sampled_nodes]))
        peer_dem = float(np.median([n.reported_demand for n in sampled_nodes]))
        false_pos_this_slot = 0
        for nid in sample_ids:
            node = nodes[nid]
            if _flagged_by_protocol(proto_name, node, twin, peer_gen, peer_dem,
                                    proto=proto, anomaly=anomalies[nid]):
                if node.honest:
                    false_pos_this_slot += 1
                    false_pos_cum += 1
                else:
                    caught_attackers.add(nid)

        # 5. consensus round
        bid = proto.propose_block()
        sched.run_until(sched.now_ms + 120000.0)
        block = proto.blocks[bid]
        wt = (time.perf_counter() - wt0) * 1000.0

        lat = (block.commit_time - block.start_time) if block.committed else 120000.0
        vset = block.validating_set or [block.proposer]
        mal_in = [v for v in vset if v in malicious]
        profit = sum(max(0.0, nodes[v].reported_generation - nodes[v].actual_generation)
                     for v in mal_in)
        t0 = block.start_time

        def rel(t, t0=t0):
            return None if t is None else t - t0

        results.append(SlotResult(
            slot=slot, proposer=block.proposer,
            latency_ms=lat, msgs_sent=net.messages_sent - msgs_before,
            throughput_tps=(tx_per_slot * 1000.0) / max(lat, 0.001),
            attackers_caught=len(caught_attackers),
            false_pos_this_slot=false_pos_this_slot,
            false_pos_cum=false_pos_cum,
            wall_clock_ms=wt,
            infiltration_pct=100.0 * len(mal_in) / len(vset),
            proposer_malicious=block.proposer in malicious,
            profit=profit,
            t_q_proposal=rel(block.t_q_proposal),
            t_q_prepared=rel(block.t_q_prepared),
            first_commit_ms=rel(block.t_first_commit),
            fast_path=block.fast_path,
            committed=block.committed,
        ))

    return results


if __name__ == "__main__":
    """Quick sanity check: one seed, N=200, 20 slots, one protocol."""
    import sys
    proto = sys.argv[1] if len(sys.argv) > 1 else "PoET2S"
    res = run_protocol_slots(proto, n_nodes=200, seed=42, n_slots=20)
    print(f"{proto} at N=200 over 20 slots:")
    print(f"  mean latency: {np.mean([r.latency_ms for r in res]):.1f} ms")
    print(f"  commit capacity (block size / latency, not used in the paper): {np.mean([r.throughput_tps for r in res]):.1f} tx/s")
    print(f"  mean msgs:    {np.mean([r.msgs_sent for r in res]):.0f}")
    print(f"  attackers caught (final): {res[-1].attackers_caught} / 30")
    print(f"  false positives (final):  {res[-1].false_pos_cum}")
    print(f"  mean wall-clock: {np.mean([r.wall_clock_ms for r in res]):.1f} ms/slot")
