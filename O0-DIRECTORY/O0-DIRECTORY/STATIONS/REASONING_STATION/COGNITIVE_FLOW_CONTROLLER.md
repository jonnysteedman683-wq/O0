---
title: "COGNITIVE_FLOW_CONTROLLER"
station: "REASONING"
priority: 8
quick_paths: ["REASONING_STATION_MAP", "STATE_SPACE_REASONING"]
tags: ["reasoning/flow", "cognitive_flow", "dual_process", "deliberation", "priority/8"]
---

# 🌊 Cognitive Flow Controller

> **Station Origin:** `[[REASONING_STATION_MAP]]` (P10)  
> **Priority:** 8  
> **Direct Bridges:** `[[STATE_SPACE_REASONING]]` (P5)

---

## 🔬 Architectural Mechanics
Implements context-aware AI reasoning intervention based on arXiv:2504.16021.

### Dual Operating Modes
1. **FLOW Mode (System 1 Execution):**
   - Engaged when confidence $\ge 0.85$ and recent success runs $\ge 3$.
   - Characteristics: High-velocity pipelined tool execution, minimal prompt verbosity, sub-quadratic overhead.
2. **DELIBERATE Mode (System 2 Intervention):**
   - Triggered upon any test failure, high ambiguity ($u > 0.35$), or critical state mutations.
   - Characteristics: Detailed chain-of-thought DAG decomposition, hypothesis tree exploration, strict pre-condition validation.
