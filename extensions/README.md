# extensions/ — Antigravity territory

This directory is owned by **Antigravity** (and any non-Hermes coding agent).
Hermes never edits here. It is deliberately **excluded** from the flywheel's
auto-commit scope, so your uncommitted work is never swept by a Hermes
promotion.

## Rules (see `AGENTS.md` at repo root)

- Edit only files under `extensions/`, `tests/extensions/`, `docs/antigravity/`.
- Never `git add -A` — stage only your own territory.
- Never run `python -m o0.main` (the flywheel).
- `git pull --rebase` before committing; prefix commits `[agy]`.
- Run `python -m pytest tests/extensions/ -q` before committing.
- Never touch `state/ledger.jsonl` or `state/memory.jsonl`.

## Layout

- `probes/` — new capability probes (mirror `o0/probes.py`).
- `connectors/` — cross-stack connectors (mirror `o0/agency.py`): UniSync ledger,
  GitHub stack probes and human-gated dispatch. See `docs/antigravity/guides/connectors.md`.
- `mesh/` — async, self-healing multi-agent engine: HLC + CRDT replicated state, typed
  envelopes over bounded mailboxes, supervisor/watchdog, sandboxed cost-aware tool runtime,
  DAG orchestrator. Stdlib-only, `mypy --strict`. See `docs/antigravity/guides/agent_mesh.md`.
- `reporting/` — modules that read `state/ledger.jsonl` and render O0's
  capability trajectory.

Each extension must be self-contained, tested, and honest. Extensions may
import from `o0.*` but must not modify it.
