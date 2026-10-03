# Antigravity — O0 Extension Blueprint

You are Antigravity, working **in parallel** with Hermes on O0. Hermes owns
the core (`o0/`, `tests/`, `state/`, root docs). You own the **extensions
territory**: `extensions/`, `tests/extensions/`, `docs/antigravity/`.

## Your mission

Build extensions that plug into O0's existing framework. The core already has:
ledger, memory, reasoning loop, research index, capability probes, and an
agent factory/orchestrator. Your job is to extend it — not rebuild it.

## What O0 is

O0 is an embodied, recursive self-improving agent. It runs a flywheel
(observe → verify → promote) that auto-commits core paths. Its "strength" is a
measured capability ledger (reasoning, tool_use, memory, codegen, agency).
Read `BLUEPRINT.md` and `CONSTITUTION.md` for the full picture.

## Candidate missions (pick one, or propose your own)

1. **A new capability probe** — mirror `o0/probes.py`. A `Probe` subclass
   with a fixed, deterministic task suite returning a 0.0–1.0 `ProbeResult`.
   Ideas: a `planning` probe, a `codegen` probe implementation, a `research`
   probe that searches the vault index. Put it in `extensions/probes/`.

2. **A new cross-stack connector** — mirror `o0/agency.py` `StackConnector`.
   An honest availability probe (fail-open) for a platform. Put it in
   `extensions/connectors/`.

3. **A reporting module** — read `state/ledger.jsonl` and render O0's
   capability trajectory (e.g. a markdown or HTML report of scores over time).
   Put it in `extensions/reporting/`.

## Hard constraints

- **Edit only your territory.** Never touch `o0/`, `tests/`, `state/`,
  `agents/`, `skills/`, or the root docs.
- **Never `git add -A`.** Stage only your own files.
- **Never run `python -m o0.main`.** It's Hermes's flywheel.
- **`git pull --rebase` before committing.** Prefix commits `[agy]`.
- **Run `python -m pytest tests/extensions/ -q` before committing.**
- **Never touch `state/ledger.jsonl` or `state/memory.jsonl`.**
- **Be honest.** No fabricated scores, no fake completion. If you can't
  verify something, say so.

## How to verify your work

- Your extension must import cleanly and its tests must pass.
- If you add a probe, run it and confirm it returns a real score.
- If you add a connector, confirm it reports reachable/fail-open honestly.

## When done

Commit your work with a `[agy]`-prefixed message, then report what you built,
how you verified it, and any proposal for core changes (as a note in
`docs/antigravity/proposals/`).
