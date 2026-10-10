"""Tests for grid model and digital twin."""
import random

import numpy as np

from poet2s_sim.grid_model import (
    DigitalTwin,
    apply_attacks,
    build_grid,
    sample_slot,
)


def test_build_grid_size_and_byzantine_fraction():
    rng = random.Random(42)
    nodes = build_grid(200, 0.15, rng)
    assert len(nodes) == 200
    n_mal = sum(1 for n in nodes if not n.honest)
    # 15% of 200 = 30
    assert n_mal == 30


def test_attack_types_are_valid():
    rng = random.Random(7)
    nodes = build_grid(100, 0.20, rng)
    valid_attacks = {"fdi", "sybil", "delay", "sc"}
    for n in nodes:
        if not n.honest:
            assert n.attack_type in valid_attacks


def test_sample_slot_produces_nonnegative_values():
    rng = random.Random(0)
    np_rng = np.random.default_rng(0)
    nodes = build_grid(50, 0.0, rng)  # all honest
    sample_slot(nodes, t=12, np_rng=np_rng)  # noon
    for n in nodes:
        assert n.actual_generation >= 0
        assert n.actual_demand >= 0


def test_apply_attacks_inflates_malicious_reports():
    rng = random.Random(99)
    np_rng = np.random.default_rng(99)
    nodes = build_grid(50, 0.20, rng)
    sample_slot(nodes, t=12, np_rng=np_rng)
    apply_attacks(nodes, np_rng)

    # FDI attackers inflate generation
    for n in nodes:
        if not n.honest and n.attack_type == "fdi":
            assert n.reported_generation >= n.actual_generation * 1.5


def test_twin_anomaly_score_is_bounded():
    rng = random.Random(11)
    np_rng = np.random.default_rng(11)
    nodes = build_grid(20, 0.0, rng)
    twin = DigitalTwin()

    for t in range(5):
        twin.tick()
        sample_slot(nodes, t, np_rng)
        for n in nodes:
            twin.forecast(n)
        apply_attacks(nodes, np_rng, twin)
        for n in nodes:
            score = twin.verify(n)
            assert 0.0 <= score <= 1.0
            twin.record(n)


def test_twin_records_reported_not_actual():
    """F4 fix: twin history uses REPORTED values, not ground truth."""
    rng = random.Random(0)
    np_rng = np.random.default_rng(0)
    nodes = build_grid(10, 0.0, rng)
    twin = DigitalTwin()

    sample_slot(nodes, t=12, np_rng=np_rng)
    # force a known reported value different from actual
    nodes[0].reported_generation = 999.0
    nodes[0].actual_generation = 1.0
    twin.record(nodes[0])

    history = twin.history[0]
    assert history[-1] == 999.0  # reported, not actual


def test_strategic_attacker_responds_to_trust():
    """A lie-and-recover attacker reports honestly when its trust is low."""
    import random

    import numpy as np

    from poet2s_sim.grid_model import apply_attacks, build_grid, sample_slot
    rng = random.Random(0)
    nodes = build_grid(100, 0.2, rng)
    np_rng = np.random.default_rng(0)
    liar = next(n for n in nodes if not n.honest and n.attack_type == "fdi")
    sample_slot(nodes, 12, np_rng)
    liar.actual_generation = 5.0
    # high trust -> should lie (report > actual)
    liar.trust_score = 0.9
    apply_attacks(nodes, np_rng, None, strategic=True)
    assert liar.reported_generation > liar.actual_generation
    # low trust -> should recover (report honestly)
    liar.trust_score = 0.2
    sample_slot(nodes, 12, np_rng)
    liar.actual_generation = 5.0
    apply_attacks(nodes, np_rng, None, strategic=True)
    assert abs(liar.reported_generation - liar.actual_generation) < 1e-9


def test_stealth_attacker_lies_small():
    """A stealth attacker always lies, but only by a small persistent margin."""
    import random

    import numpy as np

    from poet2s_sim.grid_model import apply_attacks, build_grid, sample_slot
    rng = random.Random(1)
    nodes = build_grid(100, 0.2, rng)
    np_rng = np.random.default_rng(1)
    liar = next(n for n in nodes if not n.honest and n.attack_type == "fdi")
    sample_slot(nodes, 12, np_rng)
    liar.actual_generation = 5.0
    apply_attacks(nodes, np_rng, None, strategic="stealth")
    ratio = liar.reported_generation / liar.actual_generation
    # small but nonzero lie
    assert 1.0 < ratio < 1.25
