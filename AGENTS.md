# AGENTS.md — O0 Parallel-Work Rules

This file governs **all coding agents** working on O0, including Antigravity
(`agy`) and Hermes. Read `BLUEPRINT.md` and `CONSTITUTION.md` first — they
define what O0 is and the invariants no agent may weaken.

## Why these rules exist

O0's flywheel (`python -m o0.main`) **auto-commits** the core paths below on
every promotion. If two agents edit the same files, one agent's uncommitted
work gets swept into the other's commit, or the two collide. The fix is a
**disjoint file-territory partition**: each agent owns files the other never
touches. Territories never overlap, so parallel work is safe.

## Territory ownership

| Territory | Owner | Paths |
|---|---|---|
| **Core** | Hermes | `o0/`, `tests/`, `state/`, `agents/`, `skills/`, `CONSTITUTION.md`, `BLUEPRINT.md`, `README.md`, `.gitignore` |
| **Extensions** | Antigravity | `extensions/`, `tests/extensions/`, `docs/antigravity/` |

The flywheel's auto-commit scope is `o0/`, `tests/`, `skills/`, `agents/`,
`state/`, and the root docs. **`extensions/` is deliberately excluded** — so
Antigravity's uncommitted work is never swept by a Hermes promotion.

## Hard rules (both agents)

1. **Edit only your own territory.** Hermes never edits `extensions/`;
   Antigravity never edits core paths.
2. **Never `git add -A` or `git add .`.** Stage only your own territory's
   files. A scoped `git add <your paths>` is the only allowed form.
3. **Never run `python -m o0.main` from the extensions territory.** The
   flywheel is Hermes's promotion mechanism and auto-commits core paths.
4. **`git pull --rebase` before every commit** to stay in sync with the other
   agent's commits. With disjoint territories, rebase is always clean.
5. **Commit small and often.** Prefix extension commits with `[agy]`.
6. **Run your own tests before committing.** Antigravity: `python -m pytest
   tests/extensions/ -q`. Hermes: `python -m pytest tests/ -q`.
7. **Never touch `state/ledger.jsonl` or `state/memory.jsonl`.** They are
   Hermes's append-only durable records.
8. **Need a core change?** Do not edit core directly. Write a proposal note in
   `docs/antigravity/proposals/<name>.md` and let Hermes/Jonny decide.

## Antigravity blueprint (mission)

Build **extensions** that plug into O0's existing framework. Follow the
patterns already in the core:

- **New capability probe** — mirror `o0/probes.py` (`Probe` + `ProbeResult`,
  fixed deterministic task suite, 0.0–1.0 score). Put it in
  `extensions/probes/<name>.py` with tests in `tests/extensions/`.
- **New cross-stack connector** — mirror `o0/agency.py` (`StackConnector`,
  honest availability probe, fail-open). Put it in
  `extensions/connectors/<name>.py`.
- **Reporting / dashboard** — a module that reads `state/ledger.jsonl` and
  renders O0's capability trajectory.

Each extension must be **self-contained, tested, and honest** (no fabricated
scores, no fake completion). Extensions may import from `o0.*` but must not
modify it.

## Conflict resolution

If a merge conflict ever arises (it shouldn't with disjoint territories), do
NOT self-adjudicate. Flag it and use the neutral merge-reconciler process.
