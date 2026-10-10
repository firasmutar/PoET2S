"""Tests for the discrete-event scheduler and network model."""
import random

import pytest

from poet2s_sim.sim_core import DEScheduler, Message, Network


def test_scheduler_event_ordering():
    sched = DEScheduler()
    events_fired = []

    sched.schedule(5.0, lambda: events_fired.append("b"))
    sched.schedule(2.0, lambda: events_fired.append("a"))
    sched.schedule(10.0, lambda: events_fired.append("c"))

    sched.run_until(100.0)

    assert events_fired == ["a", "b", "c"]
    assert sched.now_ms == 100.0


def test_scheduler_negative_delay_raises():
    sched = DEScheduler()
    with pytest.raises(ValueError):
        sched.schedule(-1.0, lambda: None)


def test_scheduler_drain_runs_all_events():
    sched = DEScheduler()
    counter = [0]

    for t in [1.0, 5.0, 100.0, 9999.0]:
        sched.schedule(t, lambda: counter.__setitem__(0, counter[0] + 1))

    n = sched.drain()
    assert n == 4
    assert counter[0] == 4


def test_network_broadcast_delivers_to_all_others():
    sched = DEScheduler()
    rng = random.Random(42)
    net = Network(sched, n_nodes=5, rng=rng)

    received = []
    for nid in range(5):
        net.register_handler(nid, "test", lambda msg, n=nid: received.append(n))

    net.broadcast(Message(src=0, dst=-1, msg_type="test", payload=None, size_bytes=64))
    sched.drain()

    # broadcast skips the sender
    assert sorted(received) == [1, 2, 3, 4]


def test_network_multicast_excludes_sender():
    sched = DEScheduler()
    rng = random.Random(42)
    net = Network(sched, n_nodes=10, rng=rng)
    received = []
    for nid in range(10):
        net.register_handler(nid, "m", lambda msg, n=nid: received.append(n))

    net.multicast(
        Message(src=2, dst=-1, msg_type="m", payload=None, size_bytes=64),
        recipients=[0, 1, 2, 3, 4],
    )
    sched.drain()
    assert 2 not in received
    assert set(received) == {0, 1, 3, 4}


def test_rtt_sampling_is_positive_and_at_least_min():
    sched = DEScheduler()
    rng = random.Random(7)
    net = Network(sched, n_nodes=2, rtt_min_ms=10.0, rng=rng)
    for _ in range(200):
        one_way = net._rtt_ms()
        # half-RTT = x_m / 2 / (1-u)^(1/alpha)
        # minimum is x_m/2 = 5 ms (when u=0)
        assert one_way >= 5.0 - 1e-9
