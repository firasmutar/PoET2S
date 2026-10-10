"""
Consensus protocol implementations (v21).

Each protocol is a STATE MACHINE that sends real messages and measures
finalisation latency as the simulated wall-clock time from proposer-election
to block-commit. There are NO parameterised latency models. The numbers
reported in the paper are measurements of these implementations.

Protocols implemented:
  - PoW: hashpower-weighted race + block broadcast
  - PoS: Ethereum-style stake-weighted committee attestation (C=16, 2/3 threshold)
  - PBFT: three-phase Castro-Liskov commit (V validators, 2V/3 threshold)
  - DPoS: 7 top-stake delegates, round-robin proposer, 4 acknowledgements commit
  - PoET2S: top-K trust-weighted committee (K=21), three-phase commit, 2K/3 threshold
  - +Twin variants: as above, with twin anomaly OR-flag for detection

Each protocol exposes:
  - propose_block(t): trigger one round of consensus
  - finalised_callback: invoked when the block is committed (records latency)

Latency = time from propose_block start to finalised_callback. This is
the actual measured wall-clock time of finalisation.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from poet2s_sim.grid_model import DigitalTwin, GridNode
from poet2s_sim.sim_core import DEScheduler, Message, Network

# Per-message processing cost (CPU) on top of network delay. These are module
# globals read at call time, so the latency-breakdown ablation can zero them.
COMPUTE_MS_PER_MSG = 0.05    # ed25519 verify ~0.05 ms
SIGN_MS = 0.10                # one ed25519 signature

# Message sizes. A proposal carries a block header plus the Merkle root of the
# slot's transactions; transaction bodies are assumed to have been gossiped
# through the mempool beforehand (the usual separation of data dissemination
# from ordering). run_latency_accounting.py re-runs with full block bodies.
PROPOSAL_BYTES = 1024
VOTE_BYTES = 256
TX_PER_BLOCK = 120
TX_BYTES = 250

@dataclass
class BlockRecord:
    """Records the lifecycle of one block."""
    block_id: int
    proposer: int
    start_time: float
    commit_time: float | None = None
    attestations: set[int] = field(default_factory=set)
    committed: bool = False
    rejected: bool = False
    validating_set: list[int] = field(default_factory=list)
    # time at which a quorum of replicas had received the proposal, and had
    # become "prepared" (committee protocols); used for the latency breakdown
    t_q_proposal: float | None = None
    t_q_prepared: float | None = None
    # fast-path commit (v20): whether the two-step path decided the block
    fast_path: bool | None = None
    # first time any single node can show the block is committed (for PoS and DPoS this is
    # the proposer collecting its quorum, i.e. the commit time itself)
    t_first_commit: float | None = None


class ConsensusBase:
    """Common interface for all consensus protocols."""
    name = "base"
    uses_twin = False

    def __init__(self, sched: DEScheduler, net: Network,
                 nodes: list[GridNode], twin: DigitalTwin | None = None,
                 rng: random.Random | None = None):
        self.sched = sched
        self.net = net
        self.nodes = nodes
        self.twin = twin
        self.rng = rng or random.Random()

        # block tracking
        self.blocks: dict[int, BlockRecord] = {}
        self.next_block_id: int = 0
        self.on_finalised: Callable[[BlockRecord], None] | None = None
        self.committed_latencies: list[float] = []

    def propose_block(self) -> int:
        """Subclass must implement: trigger one consensus round."""
        raise NotImplementedError

    def _finalise(self, block: BlockRecord):
        block.commit_time = self.sched.now_ms
        if block.t_first_commit is None:
            block.t_first_commit = block.commit_time
        block.committed = True
        self.committed_latencies.append(block.commit_time - block.start_time)
        if self.on_finalised:
            self.on_finalised(block)



# ---------------------------------------------------------------------------
# Per-replica quorum bookkeeping shared by PBFT and the committee protocols
# ---------------------------------------------------------------------------

def _quorum_state(members: list[int], primary: int, thresh: int) -> dict:
    st = {"members": list(members), "thresh": thresh,
          "prep": {m: set() for m in members},
          "comm": {m: set() for m in members},
          "got_proposal": set(), "prepared": set(), "local_commit": set()}
    # the primary holds its own proposal, which also serves as its prepare
    st["prep"][primary].add(primary)
    st["got_proposal"].add(primary)
    return st


def _on_proposal(proto, bid: int, replica: int, primary: int) -> None:
    st = proto.state[bid]
    st["prep"][replica].update((primary, replica))
    if replica not in st["got_proposal"]:
        st["got_proposal"].add(replica)
        block = proto.blocks[bid]
        if block.t_q_proposal is None and len(st["got_proposal"]) >= st["thresh"]:
            block.t_q_proposal = proto.sched.now_ms
    _maybe_prepared(proto, bid, replica)


def _maybe_prepared(proto, bid: int, replica: int) -> None:
    st = proto.state[bid]
    if replica in st["prepared"] or len(st["prep"][replica]) < st["thresh"]:
        return
    st["prepared"].add(replica)
    st["comm"][replica].add(replica)
    block = proto.blocks[bid]
    if block.t_q_prepared is None and len(st["prepared"]) >= st["thresh"]:
        block.t_q_prepared = proto.sched.now_ms
    proto._schedule_commit(bid, replica)
    _maybe_local_commit(proto, bid, replica)


def _maybe_local_commit(proto, bid: int, replica: int) -> None:
    st = proto.state[bid]
    if (replica not in st["prepared"] or replica in st["local_commit"]
            or len(st["comm"][replica]) < st["thresh"]):
        return
    st["local_commit"].add(replica)
    block = proto.blocks[bid]
    if block.t_first_commit is None:
        block.t_first_commit = proto.sched.now_ms
    if not block.committed and len(st["local_commit"]) >= st["thresh"]:
        proto._finalise(block)


def _mean_stake(nodes) -> float:
    return max(1e-9, sum(n.stake for n in nodes) / max(1, len(nodes)))

# ---------------------------------------------------------------------------
# PoW
# ---------------------------------------------------------------------------

class PoW(ConsensusBase):
    """Proof-of-Work: a node finds a block with probability proportional to its
    "hashpower" (here, uniform). The finder broadcasts the block to all peers.

    Latency = exponentially-distributed time-to-block + propagation time.
    Mean block time set to 600 seconds simulated (Bitcoin), but we run on a
    smaller fixed window so we use shorter mean (8s) for practical experiments.
    """
    name = "PoW"

    def __init__(self, *args, target_mean_ms: float = 8000.0, **kw):
        super().__init__(*args, **kw)
        self.target_mean_ms = target_mean_ms

    def propose_block(self) -> int:
        bid = self.next_block_id
        self.next_block_id += 1
        # uniform random proposer (every node has equal hashpower in this model)
        proposer = self.rng.randrange(len(self.nodes))
        block = BlockRecord(block_id=bid, proposer=proposer,
                            start_time=self.sched.now_ms,
                            validating_set=[proposer])
        self.blocks[bid] = block

        # exponential time to find block
        delta = self.rng.expovariate(1.0 / self.target_mean_ms)
        self.sched.schedule(delta, self._on_block_found, bid)
        return bid

    def _on_block_found(self, bid: int):
        block = self.blocks[bid]
        # broadcast block to all
        msg = Message(src=block.proposer, dst=-1, msg_type="pow_block",
                      payload=bid, size_bytes=PROPOSAL_BYTES)
        self.net.broadcast(msg)
        # block is considered "committed" once broadcast initiated (probabilistic
        # finality in real PoW, but we measure broadcast-emit time)
        self._finalise(block)


# ---------------------------------------------------------------------------
# PoS (stake-weighted committee attestation, Ethereum-style)
# ---------------------------------------------------------------------------

class PoS(ConsensusBase):
    """Proof-of-Stake with committee attestation.

    1. Stake-weighted proposer election (one node chosen by stake).
    2. Committee of C=16 nodes (stake-weighted sample) attest to the block.
    3. Block commits when 2C/3 = 11 attestations are collected.
    """
    name = "PoS"

    def __init__(self, *args, committee_size: int = 16,
                 attest_threshold_frac: float = 2 / 3, **kw):
        super().__init__(*args, **kw)
        self.C = committee_size
        self.thresh = math.ceil(attest_threshold_frac * committee_size)
        for nid in range(len(self.nodes)):
            self.net.register_handler(nid, "pos_propose", self._handle_propose)
            self.net.register_handler(nid, "pos_attest", self._handle_attest)

    def _select_proposer(self) -> int:
        weights = np.array([n.stake for n in self.nodes], dtype=float)
        weights /= weights.sum()
        return int(np.random.default_rng(self.rng.randrange(2**31)).choice(
            len(self.nodes), p=weights))

    def _select_committee(self, proposer: int) -> list[int]:
        weights = np.array([n.stake for n in self.nodes], dtype=float)
        weights[proposer] = 0  # exclude proposer
        weights /= weights.sum()
        return list(np.random.default_rng(self.rng.randrange(2**31)).choice(
            len(self.nodes), size=min(self.C, len(self.nodes) - 1),
            replace=False, p=weights))

    def propose_block(self) -> int:
        bid = self.next_block_id
        self.next_block_id += 1
        proposer = self._select_proposer()
        block = BlockRecord(block_id=bid, proposer=proposer,
                            start_time=self.sched.now_ms)
        self.blocks[bid] = block
        committee = self._select_committee(proposer)
        block.committee = committee   # type: ignore[attr-defined]
        block.validating_set = [proposer] + [int(c) for c in committee]

        # signing time at proposer, then multicast proposal to committee
        self.sched.schedule(SIGN_MS, self._send_propose, bid, proposer, committee)
        return bid

    def _send_propose(self, bid: int, proposer: int, committee: list[int]):
        msg = Message(src=proposer, dst=-1, msg_type="pos_propose",
                      payload=bid, size_bytes=PROPOSAL_BYTES)
        self.net.multicast(msg, committee)

    def _handle_propose(self, msg: Message):
        bid = msg.payload
        if bid not in self.blocks:
            return  # late or unknown
        # verify + sign attestation
        self.sched.schedule(COMPUTE_MS_PER_MSG + SIGN_MS,
                            self._send_attest, bid, msg.dst, msg.src)

    def _send_attest(self, bid: int, attester: int, proposer: int):
        m = Message(src=attester, dst=proposer, msg_type="pos_attest",
                    payload=bid, size_bytes=VOTE_BYTES)
        self.net.send(m)

    def _handle_attest(self, msg: Message):
        bid = msg.payload
        block = self.blocks.get(bid)
        if not block or block.committed:
            return
        block.attestations.add(msg.src)
        if len(block.attestations) >= self.thresh:
            self._finalise(block)


# ---------------------------------------------------------------------------
# PBFT (full three-phase Castro-Liskov, all validators)
# ---------------------------------------------------------------------------

class PBFT(ConsensusBase):
    """PBFT three-phase commit (Castro and Liskov) with per-replica quorums.

    Pre-prepare: the primary sends the proposal to all V validators.
    Prepare: each validator that accepts the pre-prepare multicasts a prepare.
    Commit: a validator that has itself received ceil(2V/3) prepares (the
      primary's pre-prepare counts as its prepare) multicasts a commit.
    A validator commits locally once it has received ceil(2V/3) commits.
    The block is final when ceil(2V/3) validators have committed locally.

    Every quorum is counted per receiving replica. (Versions up to v17 counted
    votes in one global set per block, which let a quorum form from the
    fastest links across different receivers and understated latency.)
    """
    name = "PBFT"

    def __init__(self, *args, threshold_frac: float = 2 / 3, **kw):
        super().__init__(*args, **kw)
        self.validators = [n.node_id for n in self.nodes if n.role == "validator"]
        if not self.validators:
            self.validators = [n.node_id for n in self.nodes]
        self.V = len(self.validators)
        self.thresh = math.ceil(threshold_frac * self.V)
        self.view = 0
        self.state: dict[int, dict] = {}
        for nid in range(len(self.nodes)):
            self.net.register_handler(nid, "pbft_preprep", self._h_preprep)
            self.net.register_handler(nid, "pbft_prepare", self._h_prepare)
            self.net.register_handler(nid, "pbft_commit", self._h_commit)

    def validating_set(self, bid: int) -> list[int]:
        return list(self.validators)

    def propose_block(self) -> int:
        bid = self.next_block_id
        self.next_block_id += 1
        primary = self.validators[self.view % self.V]
        self.view += 1
        block = BlockRecord(block_id=bid, proposer=primary,
                            start_time=self.sched.now_ms,
                            validating_set=list(self.validators))
        self.blocks[bid] = block
        self.state[bid] = _quorum_state(self.validators, primary, self.thresh)
        self.sched.schedule(SIGN_MS, self._send_preprep, bid, primary)
        return bid

    def _send_preprep(self, bid: int, primary: int):
        msg = Message(src=primary, dst=-1, msg_type="pbft_preprep",
                      payload=bid, size_bytes=PROPOSAL_BYTES)
        self.net.multicast(msg, self.validators)

    def _h_preprep(self, msg: Message):
        st = self.state.get(msg.payload)
        if st is None or msg.dst not in st["prep"]:
            return
        _on_proposal(self, msg.payload, msg.dst, msg.src)
        self.sched.schedule(COMPUTE_MS_PER_MSG + SIGN_MS,
                            self._send_prepare, msg.payload, msg.dst)

    def _send_prepare(self, bid: int, sender: int):
        m = Message(src=sender, dst=-1, msg_type="pbft_prepare",
                    payload=bid, size_bytes=VOTE_BYTES)
        self.net.multicast(m, self.validators)

    def _h_prepare(self, msg: Message):
        st = self.state.get(msg.payload)
        if st is None or msg.dst not in st["prep"]:
            return
        st["prep"][msg.dst].add(msg.src)
        _maybe_prepared(self, msg.payload, msg.dst)

    def _send_commit(self, bid: int, sender: int):
        m = Message(src=sender, dst=-1, msg_type="pbft_commit",
                    payload=bid, size_bytes=VOTE_BYTES)
        self.net.multicast(m, self.validators)

    def _schedule_commit(self, bid: int, replica: int):
        self.sched.schedule(COMPUTE_MS_PER_MSG + SIGN_MS,
                            self._send_commit, bid, replica)

    def _h_commit(self, msg: Message):
        st = self.state.get(msg.payload)
        if st is None or msg.dst not in st["comm"]:
            return
        st["comm"][msg.dst].add(msg.src)
        _maybe_local_commit(self, msg.payload, msg.dst)


# ---------------------------------------------------------------------------
# DPoS (7 elected delegates, round-robin proposer, single-message confirm)
# ---------------------------------------------------------------------------

class DPoS(ConsensusBase):
    """Delegated PoS with 7 top-stake delegates.

    Proposer = delegates[round_robin_index]. The proposer sends the block to the
    other six delegates; the block is committed when 4 of them have acknowledged."""
    name = "DPoS"

    def __init__(self, *args, n_delegates: int = 7, **kw):
        super().__init__(*args, **kw)
        sorted_nodes = sorted(self.nodes, key=lambda n: -n.stake)
        self.delegates = [n.node_id for n in sorted_nodes[:n_delegates]]
        self.D = len(self.delegates)
        # majority of the 7 delegates: 4 acknowledgements from the other delegates.
        # (Versions up to v20 used ceil(D/2) + 1 = 5, contrary to the stated design.)
        self.thresh = self.D // 2 + 1
        self.rr = 0
        for nid in range(len(self.nodes)):
            self.net.register_handler(nid, "dpos_block", self._h_block)
            self.net.register_handler(nid, "dpos_ack", self._h_ack)

    def propose_block(self) -> int:
        bid = self.next_block_id
        self.next_block_id += 1
        proposer = self.delegates[self.rr % self.D]
        self.rr += 1
        block = BlockRecord(block_id=bid, proposer=proposer,
                            start_time=self.sched.now_ms,
                            validating_set=list(self.delegates))
        self.blocks[bid] = block
        self.sched.schedule(SIGN_MS, self._send_block, bid, proposer)
        return bid

    def _send_block(self, bid: int, proposer: int):
        m = Message(src=proposer, dst=-1, msg_type="dpos_block",
                    payload=bid, size_bytes=PROPOSAL_BYTES)
        self.net.multicast(m, self.delegates)

    def _h_block(self, msg: Message):
        if msg.dst not in self.delegates:
            return
        self.sched.schedule(COMPUTE_MS_PER_MSG + SIGN_MS,
                            self._send_ack, msg.payload, msg.dst, msg.src)

    def _send_ack(self, bid: int, sender: int, proposer: int):
        m = Message(src=sender, dst=proposer, msg_type="dpos_ack",
                    payload=bid, size_bytes=VOTE_BYTES)
        self.net.send(m)

    def _h_ack(self, msg: Message):
        block = self.blocks.get(msg.payload)
        if not block or block.committed:
            return
        block.attestations.add(msg.src)
        if len(block.attestations) >= self.thresh:
            self._finalise(block)


# ---------------------------------------------------------------------------
# PoET2S: trust-weighted committee + three-phase commit
# ---------------------------------------------------------------------------

class PoET2S(ConsensusBase):
    """Trust-weighted committee with a three-phase commit.

    1. Committee C_t = top-K nodes by
         W_i = (w_s * s_i / s_bar + w_e * (e_i + 1)) * TTS_i ** gamma      (eq. 4)
       where s_bar is the mean stake and e_i the twin-verified energy term.
    2. Proposer drawn from C_t with probability proportional to W_i.
    3. Three-phase commit restricted to C_t, per-replica quorums of
       ceil(2K/3) = 14 of 21; final when 14 members have committed locally.
    """
    name = "PoET2S"
    uses_twin = True

    def __init__(self, *args, committee_size: int = 21,
                 w_stake: float = 0.35, w_energy: float = 0.45,
                 gamma: float = 2.5, eta: float = 0.22,
                 tts_reject: float = 0.35, threshold_frac: float = 2 / 3,
                 hybrid_detect: bool = False, veto_threshold: float = 0.5,
                 energy_offset: float = 1.0, committee_mode: str = "topk",
                 commit_mode: str = "three_phase", fast_f: int = 4,
                 fast_timeout_ms: float = 50.0, byz_withhold: bool = False, **kw):
        super().__init__(*args, **kw)
        self.K = committee_size
        self.w_s = w_stake
        self.w_e = w_energy
        self.gamma = gamma
        self.eta = eta
        self.tts_reject = tts_reject
        self.hybrid_detect = hybrid_detect
        self.veto_threshold = veto_threshold
        # energy_offset = 1 is eq. (4) as evaluated; 0 removes the per-identity
        # constant w_e that rewards identity splitting (hardened variant).
        self.energy_offset = energy_offset
        # committee_mode: 'topk' (as evaluated) or 'sortition' (K members drawn without
        # replacement with probability proportional to weight, as a VRF lottery would).
        self.committee_mode = committee_mode
        # commit_mode: 'three_phase' (as evaluated) or 'fast': a two-step path in the style of
        # FaB Paxos (Martin and Alvisi, 2006). With K >= 5f + 1 the committee decides after one
        # all-to-all round once a replica holds ceil((K + 3f + 1) / 2) accepts. Byzantine members
        # withhold their accepts; if fewer honest members remain than the fast quorum, replicas
        # time out after fast_timeout_ms and run the three-phase commit.
        self.commit_mode = commit_mode
        self.fast_f = fast_f
        self.fast_timeout_ms = fast_timeout_ms
        self.fast_q = math.ceil((committee_size + 3 * fast_f + 1) / 2)
        assert commit_mode == "three_phase" or committee_size >= 5 * fast_f + 1
        self.fast_state: dict[int, dict] = {}
        # byz_withhold: Byzantine committee members send no prepare/commit in the three-phase
        # commit (they always withhold accepts in the fast path). Default False: they vote.
        self.byz_withhold = byz_withhold
        self.threshold_frac = threshold_frac
        self.s_bar = _mean_stake(self.nodes)
        self.state: dict[int, dict] = {}
        for nid in range(len(self.nodes)):
            self.net.register_handler(nid, "poet_preprep", self._h_preprep)
            self.net.register_handler(nid, "poet_prepare", self._h_prepare)
            self.net.register_handler(nid, "poet_commit", self._h_commit)
            self.net.register_handler(nid, "poet_fp_prop", self._h_fp_prop)
            self.net.register_handler(nid, "poet_fp_acc", self._h_fp_acc)

    def base_weight(self, n: GridNode) -> float:
        return self.w_s * n.stake / self.s_bar + self.w_e * (n.energy_contribution + self.energy_offset)

    def weight(self, n: GridNode) -> float:
        return self.base_weight(n) * (n.trust_score ** self.gamma)

    def _draw(self, cands, weight_fn) -> list[int]:
        if self.committee_mode == "sortition":
            w = np.array([max(weight_fn(n), 1e-12) for n in cands])
            idx = np.random.default_rng(self.rng.randrange(2**31)).choice(
                len(cands), size=self.K, replace=False, p=w / w.sum())
            return [cands[i].node_id for i in idx]
        weighted = sorted(cands, key=lambda x: -weight_fn(x))
        return [n.node_id for n in weighted[:self.K]]

    def _committee(self) -> list[int]:
        return self._draw(list(self.nodes), self.weight)

    def validating_set(self, bid: int) -> list[int]:
        return list(self.state[bid]["members"])

    def propose_block(self) -> int:
        bid = self.next_block_id
        self.next_block_id += 1
        committee = self._committee()
        ws = np.array([max(self.weight(self.nodes[i]), 1e-12) for i in committee])
        ws /= ws.sum()
        proposer = int(np.random.default_rng(self.rng.randrange(2**31)).choice(
            committee, p=ws))
        block = BlockRecord(block_id=bid, proposer=proposer,
                            start_time=self.sched.now_ms,
                            validating_set=list(committee))
        self.blocks[bid] = block
        thresh = math.ceil(self.threshold_frac * len(committee))
        self.state[bid] = _quorum_state(committee, proposer, thresh)
        if self.commit_mode == "fast":
            honest = [m for m in committee if self.nodes[m].honest]
            if len(honest) >= self.fast_q:
                block.fast_path = True
                self.fast_state[bid] = {"members": list(committee), "acc": {m: set() for m in committee},
                                        "learned": set(), "thresh": thresh}
                self.sched.schedule(SIGN_MS, self._send_fp_prop, bid, proposer, committee)
                return bid
            block.fast_path = False
            self.sched.schedule(self.fast_timeout_ms + SIGN_MS, self._send_preprep, bid, proposer, committee)
            return bid
        self.sched.schedule(SIGN_MS, self._send_preprep, bid, proposer, committee)
        return bid

    # ---- two-step fast path ------------------------------------------------
    def _send_fp_prop(self, bid, proposer, committee):
        m = Message(src=proposer, dst=-1, msg_type="poet_fp_prop", payload=bid, size_bytes=PROPOSAL_BYTES)
        self.net.multicast(m, committee)
        if self.nodes[proposer].honest:
            self._fp_accept(bid, proposer)

    def _h_fp_prop(self, msg):
        fs = self.fast_state.get(msg.payload)
        if not fs or msg.dst not in fs["acc"]:
            return
        if self.nodes[msg.dst].honest:
            self.sched.schedule(COMPUTE_MS_PER_MSG + SIGN_MS, self._fp_accept, msg.payload, msg.dst)

    def _fp_accept(self, bid, sender):
        fs = self.fast_state[bid]
        fs["acc"][sender].add(sender)
        m = Message(src=sender, dst=-1, msg_type="poet_fp_acc", payload=bid, size_bytes=VOTE_BYTES)
        self.net.multicast(m, fs["members"])
        self._fp_maybe_learn(bid, sender)

    def _h_fp_acc(self, msg):
        fs = self.fast_state.get(msg.payload)
        if not fs or msg.dst not in fs["acc"]:
            return
        fs["acc"][msg.dst].add(msg.src)
        self._fp_maybe_learn(msg.payload, msg.dst)

    def _fp_maybe_learn(self, bid, replica):
        fs = self.fast_state[bid]
        if replica in fs["learned"] or len(fs["acc"][replica]) < self.fast_q:
            return
        fs["learned"].add(replica)
        block = self.blocks[bid]
        if block.t_first_commit is None:
            block.t_first_commit = self.sched.now_ms
        if not block.committed and len(fs["learned"]) >= fs["thresh"]:
            self._finalise(block)

    def _send_preprep(self, bid: int, proposer: int, committee: list[int]):
        m = Message(src=proposer, dst=-1, msg_type="poet_preprep",
                    payload=bid, size_bytes=PROPOSAL_BYTES)
        self.net.multicast(m, committee)

    def _h_preprep(self, msg: Message):
        st = self.state.get(msg.payload)
        if not st or msg.dst not in st["prep"]:
            return
        _on_proposal(self, msg.payload, msg.dst, msg.src)
        if self.byz_withhold and not self.nodes[msg.dst].honest:
            return
        self.sched.schedule(COMPUTE_MS_PER_MSG + SIGN_MS,
                            self._send_prepare, msg.payload, msg.dst,
                            st["members"])

    def _send_prepare(self, bid: int, sender: int, committee: list[int]):
        m = Message(src=sender, dst=-1, msg_type="poet_prepare",
                    payload=bid, size_bytes=VOTE_BYTES)
        self.net.multicast(m, committee)

    def _h_prepare(self, msg: Message):
        st = self.state.get(msg.payload)
        if not st or msg.dst not in st["prep"]:
            return
        st["prep"][msg.dst].add(msg.src)
        _maybe_prepared(self, msg.payload, msg.dst)

    def _schedule_commit(self, bid: int, replica: int):
        if self.byz_withhold and not self.nodes[replica].honest:
            return
        self.sched.schedule(COMPUTE_MS_PER_MSG + SIGN_MS, self._send_commit,
                            bid, replica, self.state[bid]["members"])

    def _send_commit(self, bid: int, sender: int, committee: list[int]):
        m = Message(src=sender, dst=-1, msg_type="poet_commit",
                    payload=bid, size_bytes=VOTE_BYTES)
        self.net.multicast(m, committee)

    def _h_commit(self, msg: Message):
        st = self.state.get(msg.payload)
        if not st or msg.dst not in st["comm"]:
            return
        st["comm"][msg.dst].add(msg.src)
        _maybe_local_commit(self, msg.payload, msg.dst)

    def update_trust(self, node: GridNode):
        """TTS_i <- (1 - eta) TTS_i + eta (1 - a_i), clipped to [0.01, 1] (eq. 3)."""
        if self.twin is None:
            return
        dev = self.twin.verify(node)
        node.trust_score = ((1 - self.eta) * node.trust_score
                            + self.eta * (1.0 - dev))
        node.trust_score = float(np.clip(node.trust_score, 0.01, 1.0))


class PoMonitor(PoET2S):
    """Veto design point, inspired by monitoring-gated consensus.

    A stylised design point, not a re-implementation of Proof-of-Monitoring
    (Weerasinghe et al., TNSM 2023), which is an SLA-monitoring consensus for
    5G service agreements. Here the twin acts as a binary gate: a node whose
    instantaneous anomaly exceeds veto_threshold is excluded for the slot, and
    survivors are ranked by the trust-free base weight. Committee size, commit
    protocol and messages are identical to PoET2S.
    """
    name = "PoMonitor"
    uses_twin = True

    def __init__(self, *args, veto_threshold: float = 0.5, **kw):
        super().__init__(*args, **kw)
        self.veto_threshold = veto_threshold

    def weight(self, n: GridNode) -> float:
        return self.base_weight(n)

    def _committee(self) -> list[int]:
        if self.twin is not None:
            survivors = [n for n in self.nodes
                         if self.twin.verify(n) <= self.veto_threshold]
        else:
            survivors = list(self.nodes)
        if len(survivors) < self.K:
            survivors = list(self.nodes)
        return self._draw(survivors, self.weight)


class EACM(PoET2S):
    """Additive energy-trust design point, inspired by EACM.

    Saleh and Cevik (Sensors 2025) rank validators by a weighted sum of
    residual device energy and a behavioural trust score, with a trust
    eligibility floor. This stylised version keeps the additive form and the
    floor but substitutes the twin-verified energy term e_i for residual
    battery energy and TTS for behavioural trust:
        score_i = alpha * e_i / e_max + beta * TTS_i,   TTS_i >= trust_floor
    Stake does not enter, as in the original.
    """
    name = "EACM"
    uses_twin = True

    def __init__(self, *args, trust_floor: float = 0.4, alpha: float = 0.5,
                 beta: float = 0.5, **kw):
        super().__init__(*args, **kw)
        self.trust_floor = trust_floor
        self.alpha = alpha
        self.beta = beta

    def weight(self, n: GridNode) -> float:
        e_max = max(1e-9, max(m.energy_contribution for m in self.nodes))
        return self.alpha * n.energy_contribution / e_max + self.beta * n.trust_score

    def _committee(self) -> list[int]:
        e_max = max(1e-9, max(m.energy_contribution for m in self.nodes))
        def score(n):
            return self.alpha * n.energy_contribution / e_max + self.beta * n.trust_score
        eligible = [n for n in self.nodes if n.trust_score >= self.trust_floor]
        if len(eligible) < self.K:
            eligible = list(self.nodes)
        weighted = sorted(eligible, key=lambda x: -score(x))
        return [n.node_id for n in weighted[:self.K]]


class RepStake(PoET2S):
    """Linear reputation design point: the gamma = 1 case of eq. (4).

    Inspired by reputation-weighted consensus (e.g. Deng et al., Sci. China
    Inf. Sci. 2024, where reputation adjusts PoW difficulty). Stylised here
    as W_i = base_i * TTS_i, identical to PoET2S except for the exponent, so
    the gap between the two isolates the exponent.
    """
    name = "RepStake"
    uses_twin = True

    def weight(self, n: GridNode) -> float:
        return self.base_weight(n) * n.trust_score


class PoSTwin(PoS):
    name = "PoS+Twin"
    uses_twin = True


class PBFTTwin(PBFT):
    name = "PBFT+Twin"
    uses_twin = True


class DPoSTwin(DPoS):
    name = "DPoS+Twin"
    uses_twin = True


CONSENSUS_CLASSES = {
    "PoW": PoW,
    "PoS": PoS,
    "PBFT": PBFT,
    "DPoS": DPoS,
    "PoS+Twin": PoSTwin,
    "PBFT+Twin": PBFTTwin,
    "DPoS+Twin": DPoSTwin,
    "PoMonitor": PoMonitor,
    "EACM": EACM,
    "RepStake": RepStake,
    "PoET2S": PoET2S,
}


def _self_test():
    """Verify each protocol can finalise a block."""
    from grid_model import build_grid

    rng = random.Random(42)
    nodes = build_grid(60, 0.15, rng)
    print(f"Self-test: {len(nodes)} nodes, "
          f"{sum(1 for n in nodes if n.role=='validator')} validators")

    for proto_name, cls in CONSENSUS_CLASSES.items():
        sched = DEScheduler()
        net = Network(sched, len(nodes), bandwidth_mbps=50.0,
                      rtt_min_ms=10.0, rng=random.Random(42))
        twin = DigitalTwin() if cls.uses_twin else None
        proto = cls(sched, net, nodes, twin, rng=random.Random(42))

        bid = proto.propose_block()
        sched.run_until(60000.0)  # 60s horizon

        block = proto.blocks[bid]
        if block.committed:
            lat = block.commit_time - block.start_time
            print(f"  {proto_name:12s}: committed in {lat:8.1f} ms, "
                  f"{net.messages_sent:5d} msgs")
        else:
            print(f"  {proto_name:12s}: NOT COMMITTED within 60s "
                  f"({net.messages_sent} msgs sent)")


if __name__ == "__main__":
    _self_test()
