# O0

**The strongest AI to ever exist** — operationally: an embodied, recursive self-improving agent governed by an immutable constitution and an append-only, sha256-bound capability ledger.

Start: read `BLUEPRINT.md` (thesis + architecture) and `CONSTITUTION.md` (invariants).

## Quick start

```bash
cd O0
python -m pytest tests/ -q     # the capability harness (regression gate)
python -m o0.main              # run one flywheel iteration (observe→verify→promote)
python -m o0.main --ledger     # verify every ledger record's sha256 integrity
python -m o0.main --index-vault    # index O0-DIRECTORY memory allocation
python -m o0.main --research "MCTS topology"  # search O0's local memory index
python -m o0.main --ml-research "transformer architecture"  # explicit HORIZONTAL ML recall
```

O0 indexes its own `O0-DIRECTORY/O0-DIRECTORY` allocation by default; override
the root with `O0_DIRECTORY_PATH`. `--research` searches this local index and
builds it on first use; when invoked with the current directory inside the
HORIZONTAL repository, it uses HORIZONTAL recall instead. Use `--ml-research`
(or `--horizontal-recall`) to explicitly search HORIZONTAL for ML/research
information from O0. Set `HORIZONTAL_ROOT` or `HORIZONTAL_SCRIPTS_DIR` to
override the sibling repository paths.

## Principles

- **Flywheel, not simulator.** O0 evolves *itself* — one verifiable promotion per iteration — not a population.
- **Constitution-bound.** O0 may rewrite any code/memory/goal; never the constitution.
- **Facts over vibes.** Nothing persists as true without a verified sha256 receipt.
- **No silent regression.** A promotion that lowers any ledger capability metric is rejected.
