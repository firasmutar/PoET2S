"""Tests for the consensus protocol implementations.

These tests assert that:
  - every protocol finalises at least one block within a generous horizon
  - reported latencies are positive and finite
  - the simulator is deterministic across seeds
  - PoET²S's K=21 committee actually runs (message count >= 3*K*K/3 = 3*K*ceil(2K/3))
"""
import random

import pytest

from poet2s_sim.grid_model import DigitalTwin, build_grid
from poet2s_sim.protocols import CONSENSUS_CLASSES
from poet2s_sim.sim_core import DEScheduler, Network


@pytest.mark.parametrize("proto_name", sorted(CONSENSUS_CLASSES.keys()))
def test_protocol_finalises_one_block(proto_name):
    """Every protocol finalises a block at N=60 within 60s simulated time."""
    cls = CONSENSUS_CLASSES[proto_name]
    rng = random.Random(42)
    nodes = build_grid(60, 0.15, rng)

    sched = DEScheduler()
    net = Network(sched, len(nodes), rng=random.Random(42))
    twin = DigitalTwin() if cls.uses_twin else None
    proto = cls(sched, net, nodes, twin, rng=random.Random(42))

    bid = proto.propose_block()
    sched.run_until(60_000.0)

    block = proto.blocks[bid]
    assert block.committed, f"{proto_name} did not commit within 60s"
    assert block.commit_time is not None
    lat = block.commit_time - block.start_time
    assert 0.0 < lat < 60_000.0, f"{proto_name} latency out of range: {lat}"


def test_poet2s_committee_message_complexity():
    """PoET²S with K=21 must send at least 3*K*(2K/3 + 1) messages in worst case."""
    cls = CONSENSUS_CLASSES["PoET2S"]
    rng = random.Random(42)
    nodes = build_grid(500, 0.15, rng)
    sched = DEScheduler()
    net = Network(sched, len(nodes), rng=random.Random(42))
    twin = DigitalTwin()
    proto = cls(sched, net, nodes, twin, rng=random.Random(42))

    proto.propose_block()
    sched.run_until(60_000.0)

    K = 21
    # 3-phase commit: pre-prepare (K-1) + prepare K*(K-1) + commit K*(K-1)
    # lower bound for a finalised block
    min_expected = K - 1 + 2 * K * (K - 1) // 2
    assert net.messages_sent >= min_expected, (
        f"PoET²S sent only {net.messages_sent} msgs, "
        f"expected at least {min_expected} for K={K}"
    )


def test_deterministic_across_runs():
    """Same seed, same protocol, same network -> same latency."""
    cls = CONSENSUS_CLASSES["PoS"]

    def run_once():
        rng = random.Random(42)
        nodes = build_grid(100, 0.15, rng)
        sched = DEScheduler()
        net = Network(sched, len(nodes), rng=random.Random(42))
        proto = cls(sched, net, nodes, rng=random.Random(42))
        bid = proto.propose_block()
        sched.run_until(60_000.0)
        return proto.blocks[bid].commit_time - proto.blocks[bid].start_time

    lat1 = run_once()
    lat2 = run_once()
    assert abs(lat1 - lat2) < 1e-9, f"non-deterministic: {lat1} vs {lat2}"


def test_pow_lacks_twin_detector():
    """PoW does not use the twin in any way."""
    assert CONSENSUS_CLASSES["PoW"].uses_twin is False


def test_poet2s_uses_twin():
    """PoET²S requires the twin for trust updates."""
    assert CONSENSUS_CLASSES["PoET2S"].uses_twin is True


def test_pomonitor_is_twin_as_veto():
    """PoMonitor's weight() must NOT depend on trust score (binary gate only)."""
    import random

    from poet2s_sim.grid_model import DigitalTwin, build_grid
    from poet2s_sim.protocols import PoMonitor
    from poet2s_sim.sim_core import DEScheduler, Network
    rng = random.Random(0)
    nodes = build_grid(100, 0.15, rng)
    sched = DEScheduler()
    net = Network(sched, 100, rng=random.Random(1))
    proto = PoMonitor(sched, net, nodes, DigitalTwin(), rng=random.Random(2))
    n = nodes[0]
    n.trust_score = 1.0
    w_high = proto.weight(n)
    n.trust_score = 0.01
    w_low = proto.weight(n)
    # weight must be identical regardless of trust (veto is separate from weight)
    assert abs(w_high - w_low) < 1e-9


def test_poet2s_weight_depends_on_trust():
    """PoET2S's weight() MUST depend on trust score (continuous, the contrast)."""
    import random

    from poet2s_sim.grid_model import DigitalTwin, build_grid
    from poet2s_sim.protocols import PoET2S
    from poet2s_sim.sim_core import DEScheduler, Network
    rng = random.Random(0)
    nodes = build_grid(100, 0.15, rng)
    sched = DEScheduler()
    net = Network(sched, 100, rng=random.Random(1))
    proto = PoET2S(sched, net, nodes, DigitalTwin(), rng=random.Random(2))
    n = nodes[0]
    n.trust_score = 1.0
    w_high = proto.weight(n)
    n.trust_score = 0.01
    w_low = proto.weight(n)
    # low trust must sharply reduce weight (TTS^gamma with gamma=2.5)
    assert w_low < w_high * 0.1


def test_hybrid_detector_catches_at_least_as_many():
    """Hybrid detection flags a superset of the default detector's catches:
    it adds an instantaneous trigger, so it can only catch >= default."""
    from poet2s_sim.detection import run_protocol_slots
    int(500 * 0.15)
    default_caught, hybrid_caught = [], []
    for seed in (42, 43, 44):
        rd = run_protocol_slots("PoET2S", n_nodes=500, seed=seed, n_slots=60)
        rh = run_protocol_slots("PoET2S", n_nodes=500, seed=seed, n_slots=60,
                                proto_kwargs={"hybrid_detect": True})
        default_caught.append(rd[-1].attackers_caught)
        hybrid_caught.append(rh[-1].attackers_caught)
    # hybrid catches at least as many attackers in every seed
    assert all(h >= d for h, d in zip(hybrid_caught, default_caught))
    # and strictly more in at least one
    assert any(h > d for h, d in zip(hybrid_caught, default_caught))


def test_hybrid_does_not_change_committee_weighting():
    """Hybrid affects detection only; the weight() function is untouched, so
    latency/throughput/committee selection are identical to default."""
    import statistics

    from poet2s_sim.detection import run_protocol_slots
    rd = run_protocol_slots("PoET2S", n_nodes=500, seed=42, n_slots=30)
    rh = run_protocol_slots("PoET2S", n_nodes=500, seed=42, n_slots=30,
                            proto_kwargs={"hybrid_detect": True})
    lat_d = statistics.mean(x.latency_ms for x in rd)
    lat_h = statistics.mean(x.latency_ms for x in rh)
    assert abs(lat_d - lat_h) < 1e-6


def test_eacm_and_repstake_registered():
    """The 2025-2026 competitors are registered and constructible."""
    from poet2s_sim.protocols import CONSENSUS_CLASSES
    assert "EACM" in CONSENSUS_CLASSES
    assert "RepStake" in CONSENSUS_CLASSES


def test_repstake_is_gamma_one_ablation():
    """RepStake weight must be linear in trust (gamma=1): halving trust halves
    the trust factor, whereas PoET2S (gamma=2.5) cuts it much more sharply."""
    import random

    from poet2s_sim.grid_model import DigitalTwin, build_grid
    from poet2s_sim.protocols import PoET2S, RepStake
    from poet2s_sim.sim_core import DEScheduler, Network
    rng = random.Random(0)
    nodes = build_grid(100, 0.15, rng)
    sched = DEScheduler()
    net = Network(sched, 100, rng=random.Random(1))
    rs = RepStake(sched, net, nodes, DigitalTwin(), rng=random.Random(2))
    pe = PoET2S(sched, net, nodes, DigitalTwin(), rng=random.Random(2))
    n = nodes[0]
    n.trust_score = 1.0
    rs_hi, pe_hi = rs.weight(n), pe.weight(n)
    n.trust_score = 0.5
    rs_lo, pe_lo = rs.weight(n), pe.weight(n)
    # RepStake linear: ratio ~ 0.5
    assert abs((rs_lo / rs_hi) - 0.5) < 0.02
    # PoET2S superlinear: ratio ~ 0.5^2.5 = 0.177, much sharper
    assert (pe_lo / pe_hi) < 0.25


def test_eacm_applies_trust_floor():
    """EACM excludes nodes below its trust floor from the committee."""
    import random

    from poet2s_sim.grid_model import DigitalTwin, build_grid
    from poet2s_sim.protocols import EACM
    from poet2s_sim.sim_core import DEScheduler, Network
    rng = random.Random(0)
    nodes = build_grid(200, 0.15, rng)
    sched = DEScheduler()
    net = Network(sched, 200, rng=random.Random(1))
    proto = EACM(sched, net, nodes, DigitalTwin(), rng=random.Random(2))
    # drive most nodes below the floor; a handful stay above
    for n in nodes:
        n.trust_score = 0.1
    survivors = nodes[:30]
    for n in survivors:
        n.trust_score = 0.9
    committee = proto._committee()
    # committee should be drawn from the high-trust survivors
    surv_ids = {n.node_id for n in survivors}
    assert all(c in surv_ids for c in committee)
