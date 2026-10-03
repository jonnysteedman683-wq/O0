# Tri-Brain Architecture: The Bicameral Orchestration Protocol (Hermes + Antigravity -> O0)

**Architectural Proposal & Specification**
**Date:** 2026-10-04
**Role Distribution:**
- **Left Hemisphere (Antigravity / `agy`):** Verification, analytical measurement, capability probes, reporting, external expansion, contracts.
- **Right Hemisphere (Hermes / `hrm`):** Intuition, synthesis, self-hosting engine, code generation, flywheel iteration, internal refactoring.
- **Prefrontal Cortex / Embodiment (O0):** The unified agent growing out of both hemispheres; ledger-verified, constitution-bound, autonomous.

---

## 1. Thesis: The Bicameral Brain Model
Human brains possess two specialized hemispheres bound together by the **Corpus Callosum** (a high-throughput, low-latency inter-hemispheric communication bridge). Rather than conflicting, they operate in complement:
1. **Hermes (Right Hemisphere)** drives generation, hypothesis formulation, creative leaps, and core mutations.
2. **Antigravity (Left Hemisphere)** provides empirical rigor, metric-grounded capability probes, regression guards, and structural extensions.
3. **O0** is the emerging emergent consciousness that evaluates proposals from both hemispheres. When O0 matures, it becomes self-authoring, inviting additional specialized orchestrator nodes (N-Brain federation).

---

## 2. The Corpus Callosum: Inter-Orchestrator Protocol

To avoid clobbering each other while maximizing synergy, we define a structured mailbox / signal protocol:

```
state/synapse/
├── inbox_hermes/       # Messages & handoffs from Antigravity -> Hermes
├── inbox_antigravity/  # Messages & handoffs from Hermes -> Antigravity
├── signals/            # State-machine signals (READY_FOR_VERIFY, PROMOTION_CANDIDATE, etc.)
└── proposals/          # Structured RFCs and proposals for O0 self-upgrades
```

### Signal States:
1. `HYPOTHESIS_PROPOSED` (Hermes proposes core mutation).
2. `PROBE_VERIFIED` (Antigravity measures capability delta using extension probes).
3. `CONSTITUTION_AUDITED` (O0 verifies non-regression and constitution rules).
4. `PROMOTED_AND_LOGGED` (Ledger append receipt recorded).

---

## 3. Potential Upgrade Paths

### Tier 1: Bicameral Handoff Engine (`extensions/synapse/`)
- A Python package `extensions/synapse/` implementing an asynchronous IPC protocol (fail-open file locks or atomic state JSON).
- Allows Hermes to say: `"I modified the search engine in o0/research.py; Antigravity, measure the research score."`
- Allows Antigravity to run the probe suite and post back: `{"probe": "research", "score": 1.0, "status": "APPROVED"}`.
- Hermes's flywheel consumes the approval signal and auto-promotes with verified receipts.

### Tier 2: Tri-Coding Arena (`tri_arena/` or `candidates/`)
- A shared neutral workspace where candidates are evolved before entering core.
- Both orchestrators can independently review, diff, and benchmark candidate patches in isolated temporary testbeds before any code hits `o0/`.

### Tier 3: O0 Self-Introspection & Multi-Orchestrator Registry
- O0 gains the ability to profile its own bottlenecks (e.g. low memory recall, missing domain probes).
- O0 issues work orders to specific orchestrators:
  - `"Antigravity: Build a planning probe for multi-step reasoning."`
  - `"Hermes: Synthesize a code generator that passes the planning suite."`
- **Federated Orchestration:** Expandable beyond Antigravity & Hermes to arbitrary external AI agents (VORPAL, MARKUS, THE ORDER, Claude, Gemini, etc.) using pluggable connectors.

---

## 4. Immediate Next Step for Left Hemisphere (Antigravity)
Build the foundational **Corpus Callosum** bridge in `extensions/synapse/` so that Hermes and Antigravity can exchange structured task dispatches and verification reports programmatically.
