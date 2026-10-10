"""
PoET2S simulator (v21): discrete-event core with explicit message passing.

This module provides the core infrastructure that the consensus protocols
will use:
  - DEScheduler: priority-queue event loop with logical time
  - Network: per-link RTT (Pareto), per-node outbound bandwidth queue
  - Node: inbox, send/receive primitives, statistics tracking

Every consensus protocol implements an actual state machine over
this infrastructure. Latency is measured as the simulated wall-clock time
from block proposal to block commit, including ALL message delays.

Differences from v8/v9 (the previous "fake" simulator):
  - block_latency_ms() is GONE. Latency is measured, not modeled.
  - Messages are real objects with size, source, dest, payload.
  - PBFT's V^2 messages actually cost V^2 * (RTT + processing) of simulated time.
  - Bandwidth-limited links queue messages, modeling congestion.
"""

from __future__ import annotations

import heapq
import random
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Event scheduler
# ---------------------------------------------------------------------------

@dataclass(order=True)
class Event:
    """A scheduled event. Comparable by time for the priority queue."""
    time_ms: float
    seq: int = field(compare=True)  # tie-breaker for stable ordering
    callback: Callable[..., Any] = field(default=None, compare=False)
    args: tuple = field(default=(), compare=False)


class DEScheduler:
    """Discrete-event scheduler.

    Time is in milliseconds (floating-point). Events are tuples (time, callback).
    The scheduler runs all events in time order until no events remain or
    until time exceeds horizon_ms.
    """

    def __init__(self):
        self.now_ms: float = 0.0
        self._heap: list[Event] = []
        self._counter: int = 0

    def schedule(self, delay_ms: float, callback: Callable, *args) -> None:
        if delay_ms < 0:
            raise ValueError(f"negative delay {delay_ms}")
        heapq.heappush(
            self._heap,
            Event(self.now_ms + delay_ms, self._counter, callback, args)
        )
        self._counter += 1

    def schedule_at(self, abs_time_ms: float, callback: Callable, *args) -> None:
        delay = max(0.0, abs_time_ms - self.now_ms)
        self.schedule(delay, callback, *args)

    def run_until(self, horizon_ms: float) -> int:
        """Run events until simulated time reaches horizon_ms.
        Returns the number of events processed."""
        n_events = 0
        while self._heap and self._heap[0].time_ms <= horizon_ms:
            ev = heapq.heappop(self._heap)
            self.now_ms = ev.time_ms
            ev.callback(*ev.args)
            n_events += 1
        # advance clock to horizon even if no more events
        self.now_ms = max(self.now_ms, horizon_ms)
        return n_events

    def drain(self) -> int:
        """Run all pending events (no horizon)."""
        n_events = 0
        while self._heap:
            ev = heapq.heappop(self._heap)
            self.now_ms = ev.time_ms
            ev.callback(*ev.args)
            n_events += 1
        return n_events


# ---------------------------------------------------------------------------
# Network model
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """A network message."""
    src: int                     # source node id
    dst: int                     # destination node id (or -1 for broadcast)
    msg_type: str                # protocol-specific tag
    payload: Any                 # payload (e.g., proposed block hash, vote)
    size_bytes: int = 256        # default 256 bytes per message
    sent_at: float = 0.0


class Network:
    """Network model with per-link RTT and per-node bandwidth queueing.

    Each message takes:
      1. Time on outbound queue at source (limited by sender bandwidth)
      2. Propagation delay (RTT/2 for one-way)
      3. Processing time at destination (~0.1 ms per message)

    RTT is sampled per send from Pareto(alpha=2, x_m=10ms) (RTT median 14.1 ms, mean 20 ms);
    the one-way delay is RTT/2 (median 7.07 ms, mean 10 ms). CPU work at a node is not
    queued: signing and verification are fixed delays before a send, and every delivery
    adds processing_ms at the receiver.
    This matches real-world Internet RTT measurements between
    geographically distributed peers.
    """

    def __init__(
        self,
        scheduler: DEScheduler,
        n_nodes: int,
        bandwidth_mbps: float = 50.0,    # per-node uplink
        rtt_min_ms: float = 10.0,
        rtt_alpha: float = 2.0,
        processing_ms: float = 0.1,
        rng: random.Random | None = None,
    ):
        self.sched = scheduler
        self.n_nodes = n_nodes
        self.bandwidth_bps = bandwidth_mbps * 1e6
        self.rtt_min = rtt_min_ms
        self.rtt_alpha = rtt_alpha
        self.proc_ms = processing_ms
        self.rng = rng or random.Random()

        # per-node next-available-send-time, models bandwidth FIFO queue
        self.next_send_time: list[float] = [0.0] * n_nodes

        # message handler: msg_type -> callback(node_id, msg)
        self.handlers: dict[int, dict[str, Callable]] = {
            i: {} for i in range(n_nodes)
        }

        # stats
        self.messages_sent: int = 0
        self.bytes_sent: int = 0
        self.broadcast_count: int = 0

    def register_handler(self, node_id: int, msg_type: str, callback: Callable):
        self.handlers[node_id][msg_type] = callback

    def _rtt_ms(self) -> float:
        """Sample a one-way delay (= RTT/2) from Pareto distribution."""
        u = self.rng.random()
        # Pareto: x = x_m / (1 - u)^(1/alpha)
        rtt = self.rtt_min / max(1e-9, (1 - u)) ** (1.0 / self.rtt_alpha)
        # one-way = RTT / 2
        return rtt / 2.0

    def send(self, msg: Message) -> None:
        """Send a unicast message. Computes outbound queueing + propagation +
        processing delay, schedules a delivery event at the receiver."""
        self.messages_sent += 1
        self.bytes_sent += msg.size_bytes
        msg.sent_at = self.sched.now_ms

        # bandwidth queuing at sender
        transmit_ms = (msg.size_bytes * 8 / self.bandwidth_bps) * 1000.0
        send_start = max(self.sched.now_ms, self.next_send_time[msg.src])
        send_done = send_start + transmit_ms
        self.next_send_time[msg.src] = send_done

        # propagation delay
        prop_ms = self._rtt_ms()

        # processing at receiver
        deliver_time = send_done + prop_ms + self.proc_ms
        delay = deliver_time - self.sched.now_ms

        self.sched.schedule(delay, self._deliver, msg)

    def broadcast(self, msg_template: Message, exclude: set | None = None) -> int:
        """Send `msg_template` to all nodes except `src` (and any in exclude).
        Returns the count of messages sent."""
        self.broadcast_count += 1
        exclude = exclude or set()
        n = 0
        for dst in range(self.n_nodes):
            if dst == msg_template.src or dst in exclude:
                continue
            # construct a per-dst copy (Pareto draws will differ per send)
            m = Message(
                src=msg_template.src,
                dst=dst,
                msg_type=msg_template.msg_type,
                payload=msg_template.payload,
                size_bytes=msg_template.size_bytes,
            )
            self.send(m)
            n += 1
        return n

    def multicast(self, msg_template: Message, recipients: list[int]) -> int:
        """Send to an explicit list of recipients. More efficient than broadcast
        for committee-style protocols."""
        n = 0
        for dst in recipients:
            if dst == msg_template.src:
                continue
            m = Message(
                src=msg_template.src,
                dst=dst,
                msg_type=msg_template.msg_type,
                payload=msg_template.payload,
                size_bytes=msg_template.size_bytes,
            )
            self.send(m)
            n += 1
        return n

    def _deliver(self, msg: Message):
        """Internal: invoke the destination node's handler for this message type."""
        h = self.handlers.get(msg.dst, {}).get(msg.msg_type)
        if h is not None:
            h(msg)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _self_test():
    """Verify scheduler + network work as expected."""
    rng = random.Random(42)
    sched = DEScheduler()
    net = Network(sched, n_nodes=10, bandwidth_mbps=50.0,
                  rtt_min_ms=10.0, rng=rng)

    received = []

    def make_handler(node_id):
        def h(msg: Message):
            received.append((node_id, msg.payload, sched.now_ms - msg.sent_at))
        return h

    for i in range(10):
        net.register_handler(i, "test", make_handler(i))

    # Node 0 broadcasts to all others
    net.broadcast(Message(src=0, dst=-1, msg_type="test", payload="hello", size_bytes=256))
    sched.drain()

    print(f"Self-test: {len(received)} messages delivered")
    print("  expected: 9 (broadcast to 9 other nodes)")
    delivery_times = [t for _, _, t in received]
    print(f"  delivery times: min={min(delivery_times):.2f} ms, "
          f"max={max(delivery_times):.2f} ms, "
          f"mean={sum(delivery_times)/len(delivery_times):.2f} ms")
    print(f"  network stats: {net.messages_sent} msgs, {net.bytes_sent} bytes")

    # Verify Pareto delays are heavy-tailed
    delays = sorted(delivery_times)
    print(f"  delay distribution: p25={delays[2]:.2f}, p50={delays[4]:.2f}, "
          f"p75={delays[6]:.2f}, p95={delays[-1]:.2f}")

    assert len(received) == 9, "broadcast should deliver to 9 nodes"
    assert all(t > 0 for t in delivery_times), "all delays should be positive"
    assert all(t >= 5.0 for t in delivery_times), "all delays >= RTT/2 = 5 ms"
    print("PASS")


if __name__ == "__main__":
    _self_test()
