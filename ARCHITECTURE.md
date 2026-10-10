# Architecture (simulator v21)

Design notes for the PoET²S simulator. Read after `README.md`. Section, equation and table numbers refer to the
revised manuscript.

## Layers

```
detection.py   run_protocol_slots(): one slot = physics → forecast → attacks → twin/trust update
               → audit-sample detection → one consensus round; records every per-slot metric
protocols.py   state machines: PoW, PoS, DPoS, PBFT, +Twin variants, PoET2S and the three
               design points (PoMonitor = veto, EACM = additive, RepStake = linear)
grid_model.py  GridNode, build_grid, sample_slot (physics), DigitalTwin, apply_attacks
sim_core.py    DEScheduler (priority-queue event loop), Network (Pareto delays, uplink queues)
```

Consensus protocols see the network and the per-node state written by the twin (TTS, e_i); the grid layer knows
nothing about consensus messages.

## Scheduler

`DEScheduler` is a single-threaded priority-queue event loop over simulated milliseconds. Events with equal time run
in the order they were scheduled, which keeps runs deterministic. Latency in the paper is the simulated time
`now_ms`, not wall-clock time.

## Network model (Section 7.2)

For each unicast `send`:

1. **Uplink queue.** Transmission takes `8 × size_bytes / 50 Mbit/s`; each node has one FIFO uplink, so a node that
   sends many messages in a burst waits for its own transmissions.
2. **Propagation.** A round-trip time is drawn per message from Pareto(α = 2, x_m = 10 ms) and halved. The one-way
   delay therefore has median 7.07 ms and mean 10 ms (round trip: median 14.1 ms, mean 20 ms). Delays are independent
   across messages; the overlay is a complete graph.
3. **Processing.** Every delivery adds 0.1 ms at the receiver.

Before sending a vote or proposal a node spends 0.10 ms signing it (`SIGN_MS`) plus 0.05 ms verifying the message
that triggered it (`COMPUTE_MS_PER_MSG`). These CPU costs are fixed delays and are not queued. Proposals carry a 1 KB
header and votes 256 B; `run_latency_accounting.py` repeats the measurement with full 30 KB bodies.

`broadcast` and `multicast` exclude the sender, so a replica counts its own vote explicitly.

## Protocols (Sections 5 and 6)

Every quorum is counted at the receiving replica (`_quorum_state`); a block is final when the stated number of
members have committed locally.

- **PoW.** Proposer drawn uniformly; block-finding time exponential with mean 8 s; the block is broadcast to all
  N − 1 peers.
- **PoS.** Stake-weighted proposer and a stake-weighted committee of 16 attesters; the block commits when the
  proposer holds 11 attestations.
- **DPoS.** The proposer rotates among the seven highest-stake delegates and sends the block to the other six; the
  block commits when 4 of them have acknowledged.
- **PBFT.** Castro–Liskov three-phase commit among the nodes registered as validators (about 15% of N), quorum
  ⌈2V/3⌉. Messages per block: 2V(V − 1) (V − 1 pre-prepares, (V − 1)² prepares, V(V − 1) commits), checked exactly
  by `run_validation.py` and the test suite.
- **PoET²S.** Weight W_i = (ω_s s_i/s̄ + ω_e (e_i + 1)) · TTS_i^γ with ω_s = 0.35, ω_e = 0.45, γ = 2.5 (Eq. 4).
  The K = 21 highest-weighted nodes form the committee and the proposer is drawn from it with probability
  proportional to W_i. Three-phase commit inside the committee with quorum q = 14; final when 14 members have
  committed. Messages per block: 2K(K − 1) = 840, independent of N.
  - `energy_offset=0` replaces (e_i + 1) by e_i (no per-identity constant); `committee_mode="sortition"` draws the K
    members without replacement with probability proportional to W_i (Section 8.10).
  - `commit_mode="fast"`: optional two-step path (FaB-style, f = 4, fast quorum ⌈(K + 3f + 1)/2⌉ = 17). Byzantine
    members withhold their accepts; if the fast quorum cannot form, members fall back to the three-phase commit after
    50 ms. `byz_withhold=True` makes Byzantine members withhold votes in the three-phase commit as well (Section 8.2).
- **Design points.** `RepStake` (linear) is PoET²S with γ = 1. `PoMonitor` (veto) excludes every node whose
  instantaneous anomaly exceeds 0.5 and fills the committee with the top K of the rest by base weight. `EACM`
  (additive) ranks nodes with TTS ≥ 0.4 by 0.5·e/e_max + 0.5·TTS and ignores stake. All three reuse the PoET²S
  committee size, commit protocol, message pattern, twin and trust update.
- **+Twin variants.** PoS+Twin, PBFT+Twin and DPoS+Twin use the baseline consensus unchanged and OR the twin flag
  (a > 0.5) onto the baseline's peer-median detector. A flag is recorded for scoring but does not remove the node from
  validation.

## Digital twin (Section 4)

- **Forecast (Eq. 1).** Generation: 0.65 × clear-sky envelope φ_i + 0.35 × the node's previous *reported*
  generation (physics only in the first slot). Demand: the node's calibrated load profile ψ_i. The twin forecasts the
  same hour as the physics (`(t - 1) % 24` after `tick()`); versions up to v20 forecast one hour ahead.
- **Anomaly (Eq. 2).** δ = 0.55 · |r^g − f^g| / max(f^g, 0.3 C_i + 0.3) + 0.45 · |r^d − f^d| / max(f^d, 0.3), and
  a = 1 / (1 + exp(−6 (δ − 0.35))).
- **History.** `record()` stores reported values only; ground truth never reaches the twin.
- **Verified energy (Eq. 4).** Reported generation is capped at 1.2 × φ_i, normalised by the mean PV capacity
  (6.5 kW) and smoothed with λ_e = 0.2.
- **Trust (Eq. 3).** For the trust-weighted schemes, every node's TTS is updated every slot:
  TTS ← clip_[0.01, 1]((1 − η) TTS + η (1 − a)), η = 0.22, TTS(0) = 1.

## Slot harness and detection (Sections 6.1 and 7.4)

For each 12-s slot `run_protocol_slots` (1) advances the twin clock, samples physics for every node and forecasts;
(2) applies attacks; (3) computes the anomaly of every node, records reports, updates e_i and, for trust-weighted
schemes, TTS; (4) evaluates the scheme's detector on a 150-node audit sample drawn from the seed's own generator, so
all schemes audit the same nodes; (5) runs one consensus round and records latency, first-commit time, messages,
committee infiltration, proposer capture and the profit proxy. Detectors are those of Table 3: peer-median deviation
thresholds 0.60 / 0.50 / 0.40 for PoS / DPoS / PBFT; a > 0.5 for the veto; TTS < 0.4 or a > 0.6 for the additive
rule; TTS < 1 − τ or a > 1 − τ (τ = 0.35) for the linear rule and PoET²S; TTS < 1 − τ or a > 0.5 for the hybrid.

## Determinism and pairing

The grid, the malicious set, the physical traces, the static attack draws and the audit sample depend only on the
seed (`random.Random(seed)` and `numpy.random.default_rng(seed)`); the network and the protocol use
`Random(seed + 1000)` and `Random(seed + 2000)`. Two schemes run with the same seed therefore face the same attack
realisation, which `test_seed_pairing_same_attack_realisation` checks, and repeated runs are bit-identical
(`test_deterministic_across_runs`). Adaptive attackers react to their own trust score, so their realisations diverge
across schemes by design.

## Out of scope

- Packet-level transport (no TCP/UDP, congestion control or MAC layer); absolute latencies have not been compared
  run for run with ns-3 or OMNeT++.
- Feeder topology, correlated weather and network partitions; dissemination cost of the committed trust state.
- PBFT view changes; the primary stays up for the run.
- A compromised twin; the threat model places it in a trusted execution environment.
- Real cryptography; signing and verification are fixed delays.
