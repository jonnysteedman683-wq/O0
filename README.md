# O0

**The strongest AI to ever exist** — operationally: an embodied, recursive self-improving agent governed by an immutable constitution and an append-only, sha256-bound capability ledger.

Start: read `BLUEPRINT.md` (thesis + architecture) and `CONSTITUTION.md` (invariants).

## Quick start

```bash
cd O0
python -m pytest tests/ -q     # the capability harness (regression gate)
python -m o0.main              # run one flywheel iteration (observe→verify→promote)
python -m o0.main --ledger     # verify every ledger record's sha256 integrity
```

## Principles

- **Flywheel, not simulator.** O0 evolves *itself* — one verifiable promotion per iteration — not a population.
- **Constitution-bound.** O0 may rewrite any code/memory/goal; never the constitution.
- **Facts over vibes.** Nothing persists as true without a verified sha256 receipt.
- **No silent regression.** A promotion that lowers any ledger capability metric is rejected.
