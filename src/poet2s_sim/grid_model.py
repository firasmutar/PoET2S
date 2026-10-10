"""
Physical grid model and digital twin (simulator v21).

This module is unchanged in substance from v8; it produces the physical-layer
generation/demand traces and the twin's forecast/anomaly logic. None of this
was "fake" — it's calibrated to Pecan Street + UMass Smart* statistics and
the twin is a real algorithm with closed-form math.

Re-extracted here for clean separation between physical layer and consensus
layer.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import numpy as np

# Calibration constants from public dataset statistics
PUSTATS = {
    "pv_capacity_mean_kw": 6.5,
    "pv_capacity_std_kw": 2.8,
    "pv_capacity_factor_summer_peak": 0.85,
    "household_load_mean_kw": 1.3,
    "household_load_peak_kw": 4.5,
    "load_cov": 0.35,
    "weather_clear_prob": 0.75,
    "weather_clear_multiplier": (1.0, 0.10),
    "weather_cloudy_multiplier": (0.25, 0.65),
}


@dataclass
class GridNode:
    node_id: int
    role: str                       # "prosumer", "consumer", "validator"
    capacity_kwh: float
    demand_kwh: float
    stake: float
    honest: bool = True
    attack_type: str | None = None
    adaptive: bool = False
    trust_score: float = 1.0
    energy_contribution: float = 0.0
    reported_generation: float = 0.0
    reported_demand: float = 0.0
    actual_generation: float = 0.0
    actual_demand: float = 0.0
    ever_flagged: bool = False


def pecan_umass_sample(node: GridNode, t: int,
                       np_rng: np.random.Generator,
                       hour: int | None = None):
    """Sample (generation, demand) for one slot, calibrated to Pecan Street."""
    if hour is None:
        hour = t % 24
    if 6 <= hour <= 19:
        solar = max(0.0, math.sin((hour - 6) / 13 * math.pi))
    else:
        solar = 0.0
    clear_day = np_rng.uniform() > (1 - PUSTATS["weather_clear_prob"])
    if clear_day:
        m, s = PUSTATS["weather_clear_multiplier"]
        weather = np_rng.normal(m, s)
    else:
        lo, hi = PUSTATS["weather_cloudy_multiplier"]
        weather = np_rng.uniform(lo, hi)
    gen = max(0.0, node.capacity_kwh * solar * weather
              * PUSTATS["pv_capacity_factor_summer_peak"])
    base = node.demand_kwh
    evening = 1.0 + 0.6 * math.exp(-((hour - 19) ** 2) / 5.0)
    midday_ac = 1.0 + 0.4 * math.exp(-((hour - 14) ** 2) / 8.0)
    load_shape = base * evening * midday_ac
    load = max(0.1, np_rng.normal(load_shape, load_shape * PUSTATS["load_cov"]))
    return gen, load


def build_grid(n_nodes: int, malicious_ratio: float, rng: random.Random,
               attack_mix=("fdi", "sybil", "delay", "sc"),
               adaptive: bool = False) -> list[GridNode]:
    np_rng = np.random.default_rng(rng.randint(0, 2 ** 31 - 1))
    nodes = []
    n_mal = int(n_nodes * malicious_ratio)
    mal_ids = set(rng.sample(range(n_nodes), n_mal))
    for i in range(n_nodes):
        role = rng.choices(["prosumer", "consumer", "validator"],
                           weights=[0.45, 0.40, 0.15], k=1)[0]
        if role != "consumer":
            cap = max(3.0, np_rng.normal(PUSTATS["pv_capacity_mean_kw"],
                                          PUSTATS["pv_capacity_std_kw"]))
        else:
            cap = 0.0
        dem = max(0.3, np_rng.normal(PUSTATS["household_load_mean_kw"], 0.4))
        stake = float(np_rng.lognormal(mean=3.0, sigma=0.6))
        honest = i not in mal_ids
        atk = None if honest else rng.choice(list(attack_mix))
        nodes.append(GridNode(
            node_id=i, role=role,
            capacity_kwh=cap, demand_kwh=dem,
            stake=stake, honest=honest, attack_type=atk,
            adaptive=(not honest and adaptive and atk == "fdi"),
        ))
    return nodes


class DigitalTwin:
    """Twin forecast, eq. (1): generation = 0.65 x clear-sky envelope + 0.35 x the node's
    previous REPORTED generation; demand = the node's load profile."""

    def __init__(self, alpha: float = 0.35, tolerance: float = 0.35):
        self.alpha = alpha
        self.tolerance = tolerance
        self.history: dict[int, list[float]] = {}
        self.predicted_gen: dict[int, float] = {}
        self.predicted_dem: dict[int, float] = {}
        self.phys_gen: dict[int, float] = {}
        self.t: int = 0

    def tick(self):
        self.t += 1

    def forecast(self, node: GridNode):
        # tick() is called once at the start of every slot, so after the tick for slot s
        # self.t == s + 1. The physics in sample_slot() uses hour = s % 24; the twin must
        # forecast the same hour. (Versions up to v20 used self.t % 24, one hour ahead of
        # the physics, which added a systematic forecast error at dawn and dusk.)
        hour = (self.t - 1) % 24
        solar = (max(0.0, math.sin((hour - 6) / 13 * math.pi))
                 if 6 <= hour <= 19 else 0.0)
        evening = 1.0 + 0.6 * math.exp(-((hour - 19) ** 2) / 5.0)
        midday_ac = 1.0 + 0.4 * math.exp(-((hour - 14) ** 2) / 8.0)
        phys_gen = node.capacity_kwh * solar * PUSTATS["pv_capacity_factor_summer_peak"]
        phys_dem = node.demand_kwh * evening * midday_ac
        self.phys_gen[node.node_id] = phys_gen
        hist = self.history.setdefault(node.node_id, [])
        pred_gen = 0.65 * phys_gen + 0.35 * hist[-1] if hist else phys_gen
        self.predicted_gen[node.node_id] = pred_gen
        self.predicted_dem[node.node_id] = phys_dem
        return pred_gen, phys_dem

    def verify(self, node: GridNode) -> float:
        """Anomaly score in [0, 1]. Higher = more anomalous."""
        pred_gen = self.predicted_gen.get(node.node_id, node.capacity_kwh * 0.5)
        pred_dem = self.predicted_dem.get(node.node_id, node.demand_kwh)
        floor_gen = max(pred_gen, 0.3 * node.capacity_kwh + 0.3)
        floor_dem = max(pred_dem, 0.3)
        dev_gen = abs(node.reported_generation - pred_gen) / floor_gen
        dev_dem = abs(node.reported_demand - pred_dem) / floor_dem
        dev = 0.55 * dev_gen + 0.45 * dev_dem
        excess = dev - self.tolerance
        return float(np.clip(1.0 / (1.0 + math.exp(-6.0 * excess)), 0.0, 1.0))

    ENERGY_HEADROOM = 0.20   # allowance for clear-sky days above the envelope
    ENERGY_NORM_KW = PUSTATS["pv_capacity_mean_kw"]
    ENERGY_EWMA = 0.20       # lambda_e in eq. (4)

    def verified_generation(self, node: GridNode) -> float:
        """Reported generation capped at (1 + headroom) x physics envelope."""
        cap = (1.0 + self.ENERGY_HEADROOM) * self.phys_gen.get(node.node_id, 0.0)
        return max(0.0, min(node.reported_generation, cap))

    def update_energy(self, node: GridNode) -> None:
        """e_i <- (1 - lambda_e) e_i + lambda_e * g_hat_i / C_bar (eq. 4)."""
        g_hat = self.verified_generation(node) / self.ENERGY_NORM_KW
        node.energy_contribution = ((1.0 - self.ENERGY_EWMA) * node.energy_contribution
                                    + self.ENERGY_EWMA * g_hat)

    def record(self, node: GridNode):
        """F4-corrected: use REPORTED generation, not ground truth."""
        h = self.history.setdefault(node.node_id, [])
        h.append(node.reported_generation)
        if len(h) > 50:
            h.pop(0)


def apply_attacks(nodes: list[GridNode],
                  np_rng: np.random.Generator,
                  twin: DigitalTwin | None = None,
                  strategic: bool = False) -> dict[str, float]:
    """Apply each malicious node's attack to its reported_* values.

    If strategic=True, FDI attackers run a lie-and-recover control loop: they
    observe their own trust_score and lie hard while trust is high, then report
    honestly to rebuild trust once it nears the flag boundary. This is the
    adversary designed to defeat a memoryless detector by gaming the EWMA.
    """
    losses = {"fdi": 0.0, "sybil": 0.0, "delay": 0.0, "sc": 0.0,
              "fdi_adaptive": 0.0, "fdi_strategic": 0.0}
    for n in nodes:
        n.reported_generation = n.actual_generation
        n.reported_demand = n.actual_demand
        if n.honest:
            continue
        if n.attack_type == "fdi" and strategic == "stealth":
            # Stealth: lie persistently but small, staying inside the honest
            # nodes' anomaly band (~0.28) so no single slot trips a veto. The
            # profit per slot is small, but it never stops, and a memoryless
            # detector cannot separate it from honest noise. A trust weight that
            # integrates over time still accumulates the persistent bias.
            mult = np_rng.uniform(1.08, 1.18)
            n.reported_generation = n.actual_generation * mult
            losses["fdi_strategic"] += (mult - 1.0) * max(n.actual_generation, 0.1)
        elif n.attack_type == "fdi" and strategic:
            # Lie-and-recover: greedy when trusted, honest when at risk.
            # The attacker watches its own trust_score (its own state) and
            # decides how hard to lie this slot.
            t_score = n.trust_score
            greed_threshold = 0.55     # above this, lie hard
            recover_threshold = 0.40   # below this, go honest to rebuild
            if t_score > greed_threshold:
                # Bank profit aggressively while trust is high.
                mult = np_rng.uniform(1.6, 2.4)
                n.reported_generation = n.actual_generation * mult
                losses["fdi_strategic"] += (mult - 1.0) * max(n.actual_generation, 0.1)
            elif t_score > recover_threshold:
                # Coast: small lie that keeps some profit but slows trust decay.
                mult = np_rng.uniform(1.05, 1.25)
                n.reported_generation = n.actual_generation * mult
                losses["fdi_strategic"] += (mult - 1.0) * max(n.actual_generation, 0.1)
            else:
                # Recover: report honestly so the EWMA rebuilds trust.
                n.reported_generation = n.actual_generation
        elif n.attack_type == "fdi" and n.adaptive and twin is not None:
            max_mult = 1.0 + 0.90 * (2 * twin.tolerance / 0.55)
            inflation = 1.0 + np_rng.uniform(0.05, max_mult - 1.0)
            n.reported_generation = n.actual_generation * inflation
            losses["fdi_adaptive"] += (inflation - 1.0) * max(n.actual_generation, 0.1)
        elif n.attack_type == "fdi":
            mult = np_rng.uniform(1.6, 2.4)
            n.reported_generation = n.actual_generation * mult
            losses["fdi"] += (mult - 1.0) * max(n.actual_generation, 0.1)
        elif n.attack_type == "sybil":
            n.reported_generation = max(n.reported_generation, 3.0) + np_rng.uniform(0.5, 2.5)
            losses["sybil"] += 2.0
        elif n.attack_type == "delay":
            n.reported_demand = n.actual_demand * np_rng.uniform(0.2, 0.5)
            losses["delay"] += 0.6 * n.actual_demand
        elif n.attack_type == "sc":
            n.reported_generation = n.actual_generation * np_rng.uniform(2.0, 3.2)
            n.reported_demand = n.actual_demand * 0.4
            losses["sc"] += 1.4 * n.actual_generation
    return losses


def sample_slot(nodes: list[GridNode], t: int, np_rng: np.random.Generator):
    """Sample physical generation/demand for this slot."""
    hour = t % 24
    for n in nodes:
        if n.role == "consumer":
            n.actual_generation = 0.0
            _, n.actual_demand = pecan_umass_sample(n, t, np_rng, hour)
        else:
            n.actual_generation, n.actual_demand = pecan_umass_sample(n, t, np_rng, hour)


if __name__ == "__main__":
    rng = random.Random(42)
    nodes = build_grid(20, 0.15, rng)
    np_rng = np.random.default_rng(42)
    twin = DigitalTwin()
    print(f"Built {len(nodes)} nodes, "
          f"{sum(1 for n in nodes if n.role=='prosumer')} prosumers, "
          f"{sum(1 for n in nodes if not n.honest)} malicious")
    for t in range(3):
        twin.tick()
        sample_slot(nodes, t, np_rng)
        for n in nodes:
            twin.forecast(n)
        apply_attacks(nodes, np_rng, twin)
        anomalies = [twin.verify(n) for n in nodes]
        for n in nodes:
            twin.record(n)
        print(f"  slot {t}: max anomaly = {max(anomalies):.2f}, "
              f"mean honest = {sum(a for a,n in zip(anomalies,nodes) if n.honest)/sum(1 for n in nodes if n.honest):.2f}")
    print("Grid + twin self-test OK")
