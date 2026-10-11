---
title: "CAPABILITY_PROBES_SUITE"
station: "TESTS"
priority: 8
quick_paths: ["TESTS_STATION_MAP", "NEURAL_NETWORK_TESTS"]
tags: ["tests/probes", "benchmarks", "evaluation", "priority/8"]
---

# 🎯 Capability Probes Suite

> **Station Origin:** `[[TESTS_STATION_MAP]]` (P10)  
> **Priority:** 8  
> **Direct Bridges:** `[[NEURAL_NETWORK_TESTS]]` (P5)

---

## 📐 Benchmark Architecture
Probes evaluate empirical skills without synthetic fabrication. Each probe returns `ProbeResult(name, score, detail)` with score bounded strictly in $[0.0, 1.0]$.

### Active Probes
1. **Research Capability Probe** (`extensions.probes.research.ResearchProbe`):
   - Measures exact index recall, query precision, metadata accuracy, and speed over the knowledge vault.
   - Baseline empirical pass rate: **0.75 (15/20 tasks)**.
2. **Planning Capability Probe** (`extensions.probes.planning.PlanningProbe`):
   - Measures DAG dependency decomposition, cycle detection, topological ordering, and priority resolution.
   - Baseline empirical pass rate: **1.00 (10/10 tasks)**.

---

## 🛡️ Monotonic Improvement Invariant
A patch or mutation is rejected if any probe score regresses by more than $\epsilon = 0.00$ without prior constitutional approval.
