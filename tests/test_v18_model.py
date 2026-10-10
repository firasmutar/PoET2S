"""Tests for the v18 corrections: per-replica quorums, twin-verified energy,
and seed pairing of attack realisations."""
import random

import numpy as np

from poet2s_sim.detection import run_protocol_slots
from poet2s_sim.grid_model import DigitalTwin, GridNode, apply_attacks, build_grid, sample_slot
from poet2s_sim.protocols import PBFT, PoET2S
from poet2s_sim.sim_core import DEScheduler, Network


def _one_block(cls, n=200, seed=3):
    rng = random.Random(seed)
    nodes = build_grid(n, 0.15, rng)
    sched = DEScheduler()
    net = Network(sched, n, rng=random.Random(seed + 1))
    proto = cls(sched, net, nodes, DigitalTwin(), rng=random.Random(seed + 2))
    bid = proto.propose_block()
    sched.run_until(60_000.0)
    return proto, bid


def test_per_replica_quorum_is_respected():
    """No replica commits locally before it has itself received a quorum of
    prepares and of commits; finality needs a quorum of local commits."""
    for cls in (PBFT, PoET2S):
        proto, bid = _one_block(cls)
        st = proto.state[bid]
        assert proto.blocks[bid].committed
        assert len(st["local_commit"]) >= st["thresh"]
        for r in st["local_commit"]:
            assert len(st["prep"][r]) >= st["thresh"]
            assert len(st["comm"][r]) >= st["thresh"]


def test_three_phase_slower_than_one_way_floor():
    """A three-phase commit needs at least three one-way hops (min 5 ms each)."""
    proto, bid = _one_block(PoET2S)
    b = proto.blocks[bid]
    assert b.commit_time - b.start_time >= 15.0
    assert b.t_q_proposal <= b.t_q_prepared <= b.commit_time


def test_verified_energy_capped_by_physics_envelope():
    twin = DigitalTwin()
    node = GridNode(node_id=0, role="prosumer", capacity_kwh=6.0, demand_kwh=1.0, stake=10.0)
    twin.t = 12                      # midday
    twin.forecast(node)
    phys = twin.phys_gen[0]
    node.reported_generation = 3.0 * phys          # gross over-report
    assert twin.verified_generation(node) <= 1.2 * phys + 1e-9
    node.reported_generation = 0.5 * phys          # honest under-production
    assert abs(twin.verified_generation(node) - 0.5 * phys) < 1e-9


def test_energy_term_is_active():
    """e_i must move away from zero for producing nodes (it was inert in v17)."""
    rng = random.Random(1)
    nodes = build_grid(100, 0.15, rng)
    np_rng = np.random.default_rng(1)
    twin = DigitalTwin()
    for t in range(12):
        twin.tick()
        sample_slot(nodes, t, np_rng)
        for n in nodes:
            twin.forecast(n)
        apply_attacks(nodes, np_rng, twin)
        for n in nodes:
            twin.update_energy(n)
    prosumers = [n for n in nodes if n.role != "consumer"]
    assert max(n.energy_contribution for n in prosumers) > 0.05
    assert all(n.energy_contribution == 0.0 for n in nodes if n.role == "consumer")


def test_seed_pairing_same_attack_realisation(monkeypatch):
    """Same seed -> the same reported values from every attacker in every slot,
    whichever scheme is running (static attacks)."""
    import poet2s_sim.detection as D
    real = D.apply_attacks
    def run(scheme):
        log = []
        def spy(nodes, np_rng, twin=None, strategic=False):
            out = real(nodes, np_rng, twin, strategic)
            log.append(tuple(round(n.reported_generation, 9) for n in nodes if not n.honest))
            return out
        monkeypatch.setattr(D, "apply_attacks", spy)
        D.run_protocol_slots(scheme, n_nodes=150, seed=7, n_slots=6)
        return log
    assert run("PoMonitor") == run("PoET2S") == run("PBFT")


def test_fast_path_keeps_selection_and_detection():
    """The two-step fast path changes commit latency only (v20)."""
    a = run_protocol_slots("PoET2S", n_nodes=500, seed=42, n_slots=30)
    b = run_protocol_slots("PoET2S", n_nodes=500, seed=42, n_slots=30, proto_kwargs={"commit_mode": "fast"})
    assert [x.infiltration_pct for x in a] == [x.infiltration_pct for x in b]
    assert a[-1].attackers_caught == b[-1].attackers_caught and a[-1].false_pos_cum == b[-1].false_pos_cum
    assert sum(x.latency_ms for x in b) < sum(x.latency_ms for x in a)


def test_fast_path_falls_back_when_too_many_byzantine():
    r = run_protocol_slots("PoMonitor", n_nodes=200, seed=7, n_slots=12, malicious_ratio=0.45,
                           proto_kwargs={"commit_mode": "fast"})
    assert any(x.fast_path is False for x in r)
    assert all(x.latency_ms > 50.0 for x in r if x.fast_path is False)


def test_twin_forecasts_the_same_hour_as_the_physics():
    """v21: the twin's clear-sky envelope must use the slot's own hour."""
    import math
    import random

    import numpy as np

    from poet2s_sim.grid_model import PUSTATS, DigitalTwin, build_grid, sample_slot
    nodes = build_grid(30, 0.0, random.Random(3))
    twin, npr = DigitalTwin(), np.random.default_rng(3)
    prod = next(n for n in nodes if n.role != "consumer")
    for slot in range(30):
        twin.tick()
        sample_slot(nodes, slot, npr)
        twin.forecast(prod)
        h = slot % 24
        env = (prod.capacity_kwh * PUSTATS["pv_capacity_factor_summer_peak"]
               * (max(0.0, math.sin((h - 6) / 13 * math.pi)) if 6 <= h <= 19 else 0.0))
        assert abs(twin.phys_gen[prod.node_id] - env) < 1e-12
        if env == 0.0:
            assert prod.actual_generation == 0.0


def test_dpos_commits_on_four_acknowledgements():
    import random

    from poet2s_sim.grid_model import build_grid
    from poet2s_sim.protocols import DPoS
    from poet2s_sim.sim_core import DEScheduler, Network
    nodes = build_grid(60, 0.0, random.Random(1))
    s = DEScheduler()
    net = Network(s, 60, rng=random.Random(2))
    p = DPoS(s, net, nodes, rng=random.Random(3))
    assert p.thresh == 4
    bid = p.propose_block()
    s.run_until(10000)
    assert p.blocks[bid].committed and len(p.blocks[bid].attestations) >= 4
