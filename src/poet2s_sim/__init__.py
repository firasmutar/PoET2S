"""PoET²S: discrete-event simulator for trust-weighted consensus.

This package provides:
    sim_core   - discrete-event scheduler + network model
    grid_model - calibrated grid + digital twin
    protocols  - PoW, PoS, PBFT, DPoS, PoS+Twin, PBFT+Twin, DPoS+Twin, PoET²S
    detection  - per-slot attack/detect/trust-update loop

Public entry points
-------------------
>>> from poet2s_sim import run_protocol_slots, CONSENSUS_CLASSES
>>> results = run_protocol_slots("PoET2S", n_nodes=200, seed=42, n_slots=20)
"""

from poet2s_sim.detection import SlotResult, run_protocol_slots
from poet2s_sim.grid_model import (
    PUSTATS,
    DigitalTwin,
    GridNode,
    apply_attacks,
    build_grid,
    pecan_umass_sample,
    sample_slot,
)
from poet2s_sim.protocols import (
    CONSENSUS_CLASSES,
    PBFT,
    ConsensusBase,
    DPoS,
    DPoSTwin,
    PBFTTwin,
    PoET2S,
    PoS,
    PoSTwin,
    PoW,
)
from poet2s_sim.sim_core import DEScheduler, Message, Network

__version__ = "0.1.0"

__all__ = [
    "DEScheduler",
    "Network",
    "Message",
    "GridNode",
    "DigitalTwin",
    "build_grid",
    "sample_slot",
    "apply_attacks",
    "pecan_umass_sample",
    "PUSTATS",
    "ConsensusBase",
    "PoW",
    "PoS",
    "PBFT",
    "DPoS",
    "PoSTwin",
    "PBFTTwin",
    "DPoSTwin",
    "PoET2S",
    "CONSENSUS_CLASSES",
    "run_protocol_slots",
    "SlotResult",
]
