---
title: "TRI_CODING_ARENA_BENCHMARKS"
station: "TESTS"
priority: 8
quick_paths: ["TESTS_STATION_MAP", "DISTRIBUTED_VERIFICATION"]
tags: ["tests/arena", "benchmarks", "sandbox", "tri_coding", "priority/8"]
---

# 🏟️ Tri-Coding Staging Arena Benchmarks

> **Station Origin:** `[[TESTS_STATION_MAP]]` (P10)  
> **Priority:** 8  
> **Direct Bridges:** `[[DISTRIBUTED_VERIFICATION]]` (P5)

---

## 🔬 Multi-Agent Staging Protocol
The Arena (`extensions.arena.runner.ArenaRunner`) serves as the pre-commit crucible where candidate patches authored by Hermes, Antigravity, or sub-agents undergo empirical validation.

### Evaluation Criteria
1. **Probe Monotonicity:** Candidate patch must meet or exceed baseline score across all capability probes ($\Delta \ge 0.0$).
2. **Deterministic Sandbox Isolation:** Executed under bounded timeout in isolated subprocess environment.
3. **Pareto Optimization:** Evaluates (Score, Speed, Compactness) via NSGA-II non-dominated sorting.
