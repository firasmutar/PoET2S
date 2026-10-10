# PoET²S simulator (v21)

Discrete-event simulator and per-seed outputs for the manuscript

> Z. S. Idan, H. A. H. Alaasam, F. H. Neamah, Y. M. H. Al-Mayali and H. Alrammahi, *PoET²S: Folding a Digital Twin into Validator
> Selection for Blockchain Consensus in Peer-to-Peer Energy Trading*, revised manuscript submitted to *Future
> Technology*.

Every protocol is a message-passing state machine. Commit latency is measured, not computed from a formula: it is
the simulated time from the start of a round to finality, with quorums counted at each receiving replica, Pareto
link delays, 50 Mbit/s FIFO uplinks, and fixed signing and verification costs (Sections 7.1 and 7.2 of the paper).
All latencies are relative values inside this simulator, not deployment predictions.

## Names in the code and in the paper

| Code | Paper | What it is |
|---|---|---|
| `PoET2S` | PoET²S | Weight (ω_s s/s̄ + ω_e(e + 1)) · TTS^γ, γ = 2.5, top-K = 21 committee (Eq. 4, Section 5) |
| `RepStake` | linear design point | Same as PoET²S with γ = 1 |
| `PoMonitor` | veto design point | Nodes with anomaly a > 0.5 excluded, top-K of the rest by base weight |
| `EACM` | additive design point | 0.5·e/e_max + 0.5·TTS, eligible if TTS ≥ 0.4 |
| `PoW`, `PoS`, `DPoS`, `PBFT` and `+Twin` variants | classical baselines | Section 6.1 and Table 3 |

The three design points borrow one selection mechanism each from the systems cited in Table 1 of the paper; they are
stylised mechanisms, not re-implementations of those systems.

## Installation and tests

```
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e .
pytest -q        # 52 tests
```

The tests check, among other things, the per-replica quorum logic, the 1.2 × envelope cap on verified energy, that
the twin forecasts the same hour as the physics, the DPoS 4-of-7 commit rule, the fast-path quorum and fallback, and
that a given seed produces identical attack realisations under every scheme.

## Reproducing the paper

Seeds are fixed in the scripts (42–71 for the main runs, 42–141 for the 100-seed run, 42–51 for the Sybil study).
Each script writes CSV files to `results/`; `make_figures_v18.py` draws every figure from those CSVs.

| Paper item | Script | Output in `results/` |
|---|---|---|
| Figure 1, Section 7.3 (network-model validation) | `run_validation.py` (figure drawn by `make_figures_v18.py`) | printed check |
| Tables 6 and 8, Figures 2a–6 | `run_main.py` | `main_per_seed.csv`, `main_summary.csv` |
| Fast path, first-commit latency, withholding (Section 8.2, Figure 2) | `run_fastpath.py` | `fastpath_main.csv` |
| Fast path across Byzantine fractions (Section 8.2) | `run_fastpath.py sweep` | `fastpath_sweep.csv` |
| Table 7 (latency breakdown, 30 KB bodies) | `run_latency_accounting.py`, `run_latency_fast.py` | `latency_breakdown.csv`, `latency_payload.csv`, `latency_fast.csv` |
| 95th/99th percentile block latency (Section 8.2) | `run_tail.py` | `latency_tail.csv` |
| Figure 7 (weight trajectory, Section 8.4) | `run_weight_trajectory.py` | `weight_trajectory.csv` |
| Figure 8 (Byzantine sweep, safety violations, Section 8.5) | `run_byzantine.py` | `byzantine_sweep.csv` |
| Figure 9 (adaptive adversaries, Section 8.6) | `run_adaptive.py` | `adaptive.csv` |
| Figure 10 (parameter sensitivity, Section 8.7) | `run_param_sensitivity.py` | `param_sensitivity.csv` |
| Table 10 (hybrid detector, Section 8.8) | `run_hybrid_ablation.py` | `hybrid_ablation.csv` |
| Figure 11 (scaling, Section 8.9) | `run_scaling.py` | `scaling.csv` |
| Table 11 and honest TTS (Section 8.10) | `run_sybil.py` | `sybil.csv`, `sybil_honest_tts.csv` |
| Table 12 (Sybil countermeasures) | `run_sybil_hardening.py`, `run_sybil_sortition.py` | `sybil_hardening.csv`, `sybil_sortition.csv` |
| Main experiment with offset 0, top-K or sortition (Section 8.10) | `run_hardening.py` | `hardened.csv` |
| Figure 12 (matched false-positive cost, Section 8.11) | `run_matched_fp.py` | `matched_fp.csv` |
| Tables 9, 13 and A1 (paired tests, composite) | `run_stats.py` | `stats_tests.csv`, `composite_*.csv`, `infiltration_pairs.csv` |
| 100-seed comparison and safety-violation tests (Sections 8.3, 8.5) | `run_seeds100.py`, then `run_stats_v19.py` | `seeds100.csv`, `stats_v19.csv` |
| All figures | `make_figures_v18.py` | `figures_v18/fig01–fig12*.png` |

Run `run_stats.py` and `run_stats_v19.py` after the simulation scripts, and `make_figures_v18.py` last.
`python scripts/verify_claims.py` recomputes 104 numbers quoted in the paper from these CSVs and reports any
mismatch; it exits with a non-zero status if one fails.

Some CSVs keep a `throughput_tps` column. It is the block size divided by the commit latency, a rescaled latency
rather than a sustained rate, and the paper does not report it (Section 7.4).

## Main results (N = 500, 15% Byzantine, 30 seeds, mean ± SD; Tables 6 and 8)

| Scheme (paper name) | Latency (ms) | Caught (%) | FP / caught | Infiltration (%) | Proposer capture (%) |
|---|---:|---:|---:|---:|---:|
| PoW | 8,033 ± 988 | 0.0 | — | 13.9 ± 4.2 | 13.9 ± 4.2 |
| PoS | 20.8 ± 0.4 | 100.0 | 51.9 ± 1.6 | 15.2 ± 1.4 | 14.4 ± 4.5 |
| PoS+Twin | 20.8 ± 0.4 | 100.0 | 54.8 ± 1.4 | 15.2 ± 1.4 | 14.4 ± 4.5 |
| DPoS | 19.0 ± 0.5 | 100.0 | 58.6 ± 1.3 | 13.3 ± 11.8 | 13.3 ± 12.1 |
| DPoS+Twin | 19.0 ± 0.5 | 100.0 | 60.8 ± 1.2 | 13.3 ± 11.8 | 13.3 ± 12.1 |
| PBFT | 38.9 ± 1.3 | 100.0 | 66.4 ± 1.2 | 15.1 ± 4.4 | 15.3 ± 4.6 |
| PBFT+Twin | 38.9 ± 1.3 | 100.0 | 67.9 ± 1.2 | 15.1 ± 4.4 | 15.3 ± 4.6 |
| Veto (`PoMonitor`) | 30.2 ± 0.2 | 91.7 ± 3.1 | 9.7 ± 0.6 | 10.8 ± 3.6 | 10.2 ± 4.6 |
| Additive (`EACM`) | 30.2 ± 0.2 | 75.0 ± 4.8 | 6.0 ± 0.6 | 9.4 ± 3.5 | 8.7 ± 5.8 |
| Linear (`RepStake`) | 30.2 ± 0.2 | 91.0 ± 2.7 | 13.9 ± 0.9 | 3.8 ± 2.9 | 4.4 ± 4.8 |
| PoET²S | 30.2 ± 0.2 | 91.0 ± 2.7 | 13.9 ± 0.9 | 2.6 ± 1.9 | 2.7 ± 2.9 |

Other headline numbers in the paper, all reproducible from the scripts above:

- Optional two-step fast path: 26.8 ± 1.1 ms; first commit proof 21.2 ms (PoS 20.8, DPoS 19.0, PBFT 36.1 ms).
- 100 seeds: infiltration 3.15% for PoET²S against 4.99% for the linear rule (37% lower, Holm-adjusted p = 7.2 × 10⁻⁹).
- Blocks whose committee is at least one-third Byzantine, at 45% Byzantine nodes: 2.4% (PoET²S), 10.7% (linear),
  47.1% (additive), 64.4% (veto).
- Hybrid detector: 94.0% caught at 16.9 false positives per catch.
- Weighted sortition with offset 0 raises PoET²S infiltration to 7.7% ± 1.1%.

## Version history

**v21 (results in the revised paper).** Code audit: the twin forecast now uses the same hour as the physics
(`(t - 1) % 24` after the slot tick; earlier versions forecast one hour ahead); DPoS commits on 4 delegate
acknowledgements, as documented (earlier versions required 5); optional `byz_withhold` for the three-phase commit;
every slot is checked to have committed. All results were recomputed. A later review pass made the Wilcoxon tests
treat paired differences that are equal up to floating-point noise as ties (differences rounded to 1e-9), which
changed four Holm p-values without changing any conclusion; added `run_tail.py`; corrected the PBFT reference count
in `run_validation.py` to 2V(V − 1).

**v20.** Optional two-step fast path (`commit_mode="fast"`, FaB-style, f = 4 for K = 21, fast quorum 17, fallback to
the three-phase commit after 50 ms; Byzantine committee members withhold accepts); first-commit latency recorded for
every scheme.

**v19.** `energy_offset` (1 = Eq. 4 as evaluated; 0 removes the per-identity constant) and `committee_mode`
(`topk` or weighted `sortition`); safety-violation metric; 30-seed Byzantine and sensitivity sweeps.

**v18.** Quorums counted per receiving replica (v17 used one global vote set per block, which understated latency);
the verified energy term e_i updated every slot (it was inert in v17) and capped at 1.2 × the physical envelope; one
slot harness for all schemes with identical attack realisations per seed; throughput removed as a metric.

**v15–v17** produced the first submission. Their outputs are kept in `legacy/` for reference only (see
`legacy/README.md`); none of them is used in the revised paper.

## Repository layout

```
src/poet2s_sim/   sim_core.py (scheduler, network), grid_model.py (grid, twin, attacks),
                  protocols.py (all schemes), detection.py (slot harness and metrics), cli.py
scripts/          one script per experiment (table above), make_figures_v18.py, verify_claims.py
results/          CSV outputs used in the paper; figures_v18/ holds the figures
tests/            pytest suite
docs/             ARCHITECTURE.md (design notes)
legacy/           first-submission and pre-audit outputs, not used in the paper
```

## Licence and citation

MIT licence (`LICENSE`). Citation metadata is in `CITATION.cff`. The repository URL and archive DOI will be added
when the repository is published.
