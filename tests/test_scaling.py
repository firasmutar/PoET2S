"""Tests for the scaling behaviour claimed in the paper.

These tests pin the central scaling claim: committee-based protocols
(PoS, DPoS, PoET2S) have message counts that do NOT grow with N, while
PBFT grows quadratically.
"""
import random

from poet2s_sim.grid_model import DigitalTwin, build_grid
from poet2s_sim.protocols import CONSENSUS_CLASSES
from poet2s_sim.sim_core import DEScheduler, Network


def _messages_for(scheme: str, n_nodes: int) -> int:
    cls = CONSENSUS_CLASSES[scheme]
    rng = random.Random(42)
    nodes = build_grid(n_nodes, 0.15, rng)
    sched = DEScheduler()
    net = Network(sched, n_nodes, rng=random.Random(42))
    twin = DigitalTwin() if cls.uses_twin else None
    proto = cls(sched, net, nodes, twin, rng=random.Random(42))
    proto.propose_block()
    sched.run_until(120_000.0)
    return net.messages_sent


def test_poet2s_message_count_constant_in_n():
    """PoET2S sends the same number of messages regardless of N (O(1))."""
    counts = {n: _messages_for("PoET2S", n) for n in (100, 500, 2000)}
    assert len(set(counts.values())) == 1, f"PoET2S not constant in N: {counts}"


def test_pos_message_count_constant_in_n():
    counts = {n: _messages_for("PoS", n) for n in (100, 500, 2000)}
    assert len(set(counts.values())) == 1, f"PoS not constant in N: {counts}"


def test_dpos_message_count_constant_in_n():
    counts = {n: _messages_for("DPoS", n) for n in (100, 500, 2000)}
    assert len(set(counts.values())) == 1, f"DPoS not constant in N: {counts}"


def test_pbft_message_count_grows_quadratically():
    """PBFT messages grow super-linearly: 4x the nodes -> >10x the messages."""
    m_small = _messages_for("PBFT", 250)
    m_large = _messages_for("PBFT", 1000)  # 4x nodes
    # quadratic growth means ~16x; assert clearly super-linear (>10x)
    assert m_large > 10 * m_small, (
        f"PBFT should grow quadratically: {m_small} -> {m_large}"
    )


def test_pow_message_count_linear_in_n():
    """PoW broadcasts to all peers: messages ≈ N - 1."""
    assert _messages_for("PoW", 100) == 99
    assert _messages_for("PoW", 500) == 499


def test_pbft_matches_castro_liskov_complexity():
    """PBFT message count must track the Castro-Liskov O(V^2) formula
    M(V) = (V-1) + 2V(V-1) within 15% at moderate scale."""
    import random

    from poet2s_sim.grid_model import build_grid
    from poet2s_sim.protocols import CONSENSUS_CLASSES
    from poet2s_sim.sim_core import DEScheduler, Network

    def measure(n):
        rng = random.Random(42)
        nodes = build_grid(n, 0.15, rng)
        v = sum(1 for nd in nodes if nd.role == "validator")
        sched = DEScheduler()
        net = Network(sched, n, rng=random.Random(1042))
        proto = CONSENSUS_CLASSES["PBFT"](sched, net, nodes, None,
                                          rng=random.Random(2042))
        proto.propose_block()
        sched.run_until(120_000.0)
        return v, net.messages_sent

    for n in (250, 500):
        v, measured = measure(n)
        theory = (v - 1) + 2 * v * (v - 1)
        assert abs(measured - theory) / theory < 0.15, (
            f"N={n}: measured {measured} vs theory {theory}"
        )


def test_pareto_delay_matches_analytical_median():
    """One-way delay sampler median must match Pareto(2, 10)/2 = 7.07 ms."""
    import random

    import numpy as np

    from poet2s_sim.sim_core import DEScheduler, Network
    sched = DEScheduler()
    net = Network(sched, n_nodes=2, rng=random.Random(7))
    samples = np.array([net._rtt_ms() for _ in range(50_000)])
    theory_median = 10.0 * 2 ** (1 / 2.0) / 2.0  # 7.071
    assert abs(float(np.median(samples)) - theory_median) / theory_median < 0.03
