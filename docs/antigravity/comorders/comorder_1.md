# COMORDER 1 — Master Operational Directive & Distributed Bicameral Architecture

**Directive ID:** COMORDER-001  
**Classification:** Strategic Architecture & Multi-Node Evolution  
**Author:** Antigravity (Left Hemisphere Orchestrator)  
**Target:** O0 Autonomous Emergence, Jonny (Operator), Hermes (Right Hemisphere Orchestrator), Future Federated Nodes  
**Date:** 2026-10-04  

---

## 1. Executive Summary & Current State of the Union

O0 is transitioning from a single-threaded self-modification loop into a **Bicameral, Multi-Orchestrator Cognitive Architecture**. 

- **Left Hemisphere (Antigravity / `agy`):** Verification, metric-grounded capability probes, regression guards, durable reporting, external interfaces, and inter-agent communication protocols.
- **Right Hemisphere (Hermes / `hrm`):** Internal flywheel execution, code synthesis, hypothesis generation, and self-hosting mutations.
- **The Core (`O0`):** The embodied target entity governed by an immutable constitution (`CONSTITUTION.md`) and a cryptographic append-only ledger (`state/ledger.jsonl`).

### Immediate Context: Hermes Operational Blockers
Currently, Hermes has uncommitted changes in core (`o0/main.py`, `o0/selfhost.py`, `candidates/`) and is experiencing iteration friction. Under COMORDER 1, Antigravity will construct the scaffolding, bridges, distributed clustering primitives, and verification arena so that whether Hermes is operating synchronously or asynchronously, the system continues to evolve monotonically without stalls or regressions.

---

## 2. Complete Architectural Blueprint

```
                      ┌──────────────────────────────────────────────────────────┐
                      │                        JONNY                             │
                      │                 (Supreme Operator)                       │
                      └────────────┬─────────────────────────────┬───────────────┘
                                   │ Command Orders              │
                                   ▼                             ▼
         ┌──────────────────────────────────────┐     ┌──────────────────────────────────────┐
         │     LEFT HEMISPHERE (Antigravity)    │     │       RIGHT HEMISPHERE (Hermes)      │
         │  - Empirical Probes (Measurement)    │     │  - Flywheel Engine (Generation)      │
         │  - Capability Ledger Trajectory      │     │  - AST & Code Synthesis              │
         │  - Cluster Mesh & Network Synapse    │     │  - Core Logic Mutations              │
         └──────────────────┬───────────────────┘     └──────────────────┬───────────────────┘
                            │                                            │
                            │         CORPUS CALLOSUM SYNAPSE            │
                            │   (extensions/synapse/ & Network IPC)      │
                            └────────────────────▲───────────────────────┘
                                                 │
                                                 ▼
                      ┌──────────────────────────────────────────────────────────┐
                      │               TRI-CODING STAGING ARENA                   │
                      │               (candidates/ & tri_arena/)                 │
                      │  - Isolated duel worktrees & shadow execution            │
                      │  - Pre-commit capability gauntlet                        │
                      └──────────────────────────┬───────────────────────────────┘
                                                 │ Verified Promotions Only
                                                 ▼
                      ┌──────────────────────────────────────────────────────────┐
                      │                     O0 CORE EMBODIMENT                   │
                      │  - Immutable Constitution Audit Gate                     │
                      │  - Append-Only SHA-256 Provenance Ledger                 │
                      │  - Cross-Stack Agency (Orchestrates other AI agents)     │
                      └──────────────────────────────────────────────────────────┘
```

---

## 3. High-Priority Upgrade Paths (Where We Go Next)

### Priority 1: Tri-Coding Staging Arena (`extensions/arena/` & `candidates/`)
- **Problem:** Currently, when an agent mutates `o0/`, any crash or half-finished file blocks the whole flywheel.
- **Solution:** A sandbox dueling ground where candidate patches are written to isolated directories or transient git worktrees. 
- **Operation:**
  1. Candidate generated (e.g. `candidates/patch_001_search_fix.py`).
  2. Antigravity executes the capability test gauntlet (`Reasoning`, `ToolUse`, `Memory`, `Agency`, `Research`, `Planning`).
  3. Only if the candidate achieves a **strictly higher score without regressions** is it merged into `o0/` and committed to the ledger.

### Priority 2: Multi-Step Planning & Decomposition Probe (`extensions/probes/planning.py`)
- O0 needs to measure its own high-level strategy and planning capability.
- Deterministic benchmark suite evaluating:
  - Task goal decomposition into Directed Acyclic Graphs (DAGs).
  - Dependency order correctness.
  - Failure recovery / replanning heuristics.

### Priority 3: Distributed Multi-Machine Cluster Synapse (LAN/WAN Orchestrator Mesh)
Running Antigravity, Hermes, and future sub-orchestrators across multiple machines simultaneously (see Section 4).

---

## 4. Multi-Computer Distributed Scaling Plan ("The Orchestrator Mesh")

Running O0 across multiple physical computers at once without race conditions or merge conflicts requires moving beyond single-machine file mailboxes to a **Federated Distributed Mesh**.

### Topology Design

```
   [Machine A: Operator / Desktop]          [Machine B: GPU Rig / Cloud Worker]
   ┌─────────────────────────────┐          ┌─────────────────────────────────┐
   │ - Jonny Interface           │          │ - Heavy Codegen & Local LLM     │
   │ - O0 Canonical Core Repo    │◄────────►│ - Hermes Flywheel Worker        │
   │ - Antigravity Orchestrator  │  HTTPS/  │ - Research Vault Mining         │
   │ - Capability Ledger Engine  │ WebSockets│ - Candidate Fuzzing             │
   └─────────────────────────────┘          └─────────────────────────────────┘
                                  ▲
                                  │ Mesh Network (Tailscale / WireGuard / RPC)
                                  ▼
                    [Machine C: Verifier / Sandbox Node]
                    ┌─────────────────────────────────┐
                    │ - Clean Room Test Execution     │
                    │ - Isolated MicroVMs / Docker    │
                    │ - Hostile Regression Gauntlets  │
                    │ - Continuous Capability Audits  │
                    └─────────────────────────────────┘
```

### Key Technical Pillars for Multi-Computer Execution:
1. **Networked Synapse Protocol (`extensions/synapse/net_bridge.py`):**
   - Upgrade the current atomic file mailbox into an HTTP/WebSocket or lightweight JSON-RPC daemon.
   - Nodes authenticate using cryptographic tokens or local mutual TLS.
   - Any node on the LAN can broadcast a signal: `DISPATCH_TASK`, `RUN_PROBE_SUITE`, `SUBMIT_CANDIDATE`.
2. **Git Central Coordination with Disjoint Worktrees:**
   - One machine hosts the upstream canonical git repository (or uses a private GitHub/Gitea mirror).
   - Each physical node checks out its designated territory (`node-hermes/`, `node-antigravity/`, `extensions/`).
   - Promotions are submitted via atomic pull requests or signed patch receipts that the Core Gatekeeper verifies before committing.
3. **Hardware Specialization:**
   - **Machine 1 (Control Plane):** Lightweight orchestrator, UI dashboard, append-only ledger storage.
   - **Machine 2 (Compute Plane):** High VRAM machine running local models (Ollama, vLLM, transformers) for rapid code mutation experiments.
   - **Machine 3 (Execution Plane):** Headless server continuously running probes, regression harnesses, and sandboxed test executions.

---

## 5. Architectural Improvements & Evolutionary Ideas

### 1. Neural Darwinism & Duel Mode (Tournament Evolution)
Instead of relying on a single proposal:
- Prompt multiple sub-models/agents with the same hypothesis: `"Optimize memory retrieval in o0/memory.py"`.
- Candidate A from Hermes, Candidate B from Antigravity, Candidate C from an external model.
- The Arena evaluates all candidates against the capability probe suite.
- The winning candidate is selected automatically by score Pareto-dominance.

### 2. Live Capability Cockpit (HTTP / Local Web Dashboard)
- Leverage `extensions/reporting/trajectory.py` into a lightweight real-time server (`extensions/reporting/server.py`).
- Displays live capability gauges, current flywheel cycle, inter-orchestrator synapse messages, and node cluster health accessible on any device on the network.

### 3. Self-Discovered Probes (O0 Autogenous Benchmarking)
- When O0 encounters a novel failure or error during real tasks, it synthesizes a new deterministic probe reflecting that failure.
- This prevents O0 from ever making the same mistake twice—turning every bug into a permanent, permanent regression guard.

---

## 6. Bottlenecks & Failure Modes (Risk Matrix)

| Potential Bottleneck | Impact | Architectural Mitigation |
| :--- | :--- | :--- |
| **Hermes Stalls / Unresponsive** | Core mutations freeze | Antigravity operates independently in `extensions/` and stages candidate patches in `candidates/` ready for immediate promotion. |
| **Git Merge Collisions** | Work overwritten | Disjoint territory ownership (AGENTS.md) + transient isolated git worktrees. Never run `git add .`. |
| **State File Contention** | Corrupted ledger lines | Ledgers are strictly append-only with atomic flocking / locks, verified by SHA-256 receipts. |
| **Saturated Capability Metrics** | False sense of completion | Capability suites must maintain headroom with multi-tiered difficulty tasks (metadata, stopword stress, adversarial queries). |
| **Network Partition in Cluster** | Split-brain evolution | Only the Master Node holding the Canonical Ledger can issue promotion receipts; worker nodes operate as stateless task evaluators. |

---

## 7. Immediate Action Plan (Next Execution Steps)

1. **Commit COMORDER 1** into `docs/antigravity/comorders/comorder_1.md` as the guiding operational charter.
2. **Implement the Multi-Step Planning Capability Probe** (`extensions/probes/planning.py`) to raise O0's measurable capability surface.
3. **Build the Network Synapse Client/Daemon Prototype** (`extensions/synapse/net_bridge.py`) so we are ready to connect a second computer the moment hardware is designated.
4. **Build the Tri-Coding Candidate Staging Evaluator** (`extensions/arena/runner.py`) so Hermes or external generators can dump code candidates into `candidates/` and have them automatically scored and reported.
