# Proposal: wire O0 core onto the agent mesh

**Status:** proposed — for Hermes / Jonny to decide (AGENTS.md rule 8).
**Author:** Antigravity territory. **Depends on:** `extensions/mesh` (merged separately).

The mesh is built and tested as a self-contained extension. Making O0 itself run *on* it requires
core changes that Antigravity may not make. This note lists them, smallest-risk first, so each
can be a separate, flywheel-verified promotion.

## 1. Reasoning loop tool calls through `ToolRuntime` (low risk)

`o0/reasoning.py` runs shell tasks directly. Route them through a `ToolRuntime` with a
`subprocess_tool` per task class. Gains: schema-checked inputs/outputs, timeouts that actually
kill, retry with parameter mutation, breaker per tool, cost accounting. Ledger impact: a new
probe metric `tool_recovery_rate` (successes after ≥1 retry / total) — strictly additive.

## 2. Agency dispatch as mesh actors (medium risk)

`o0/agency.py` orchestrator dispatch → `Orchestrator` + `MeshNode`. Each stack connector becomes a
`WorkerActor`; human-gated dispatch (`extensions/connectors/dispatch.py`) stays the only path that
leaves the process, so constitution value 5 is unchanged.

## 3. Replace file-mailbox Synapse with a mesh `Transport` (medium risk)

`extensions/synapse/bridge.py` writes mailboxes under `state/synapse/` (core territory) with
second-resolution, collision-prone message ids and no schema checks. A `SynapseTransport`
implementing the `Transport` protocol over `extensions/synapse/net_bridge.py` gives typed,
deduplicated, HLC-ordered delivery between machines. Requires agreeing on a non-`state/` spool
directory or a core-owned one.

## 4. Mesh telemetry → ledger evidence (needs constitution review)

Supervisor/tool telemetry counters could become `[VERIFIED]` evidence in ledger records
(e.g. "promotion survived chaos suite with 0 lost messages"). This touches value 2 (facts over
vibes) and value 4 (append-only ledger) — it must be Hermes-authored, with the counters
reproduced by a deterministic probe rather than copied from a live run.

## 5. Harden `extensions/circuit` Tier 3 — **done** (`agy/test-isolation-and-tier3-sandbox`)

`ResilientCircuitBreaker` Tier 3 calls `exec()` on a repaired code payload in-process with full
builtins. That is arbitrary code execution inside O0. Tier 3 now runs repaired code in an isolated `python -I`
child (scrubbed env, rlimits, hard kill on timeout, JSON-only boundary), keeping the 4-tier ladder.

## Non-goals

No change to `CONSTITUTION.md`, `BLUEPRINT.md`, or `state/*.jsonl`. No new runtime dependencies.
