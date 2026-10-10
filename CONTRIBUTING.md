# Contributing

Thank you for your interest in PoET²S! Here's how to get started.

## Development setup

```bash
git clone <repository URL>   # added when the repository is published
cd poet2s-sim
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,plot]"
pytest
```

## Coding conventions

- Python 3.9+ syntax. Type hints encouraged but not required everywhere.
- Run `ruff check src/ tests/` before submitting. CI (`.github/workflows/ci.yml`) fails on lint errors.
- Keep modules layered: `sim_core` ← `grid_model`, `protocols` ← `detection`. Don't add upward dependencies.

## Adding a consensus protocol

1. Subclass `ConsensusBase` in `src/poet2s_sim/protocols.py`.
2. Register the class in the `CONSENSUS_CLASSES` dict at the bottom of the file.
3. The existing parametrised test in `tests/test_protocols.py` will run your protocol automatically.

## Adding an attack family

1. Add a branch in `apply_attacks` (`src/poet2s_sim/grid_model.py`).
2. Extend the `attack_mix` tuple in `build_grid`.
3. The detection harness will measure your attack against every detector with no further changes.

## Submitting changes

1. Fork the repo and create a feature branch.
2. Make focused commits with clear messages.
3. Run `pytest` and `ruff check src/ tests/` locally.
4. Open a pull request describing the change and any new benchmarks.

## Reporting issues

Please include:
- Python version (`python --version`)
- OS
- Minimal command/script that reproduces the issue
- Full error traceback if applicable

## License

By contributing you agree that your contributions will be licensed under the MIT License.
