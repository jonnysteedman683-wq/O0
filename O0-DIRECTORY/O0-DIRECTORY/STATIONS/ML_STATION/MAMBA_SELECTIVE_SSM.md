---
title: "MAMBA_SELECTIVE_SSM"
station: "ML"
priority: 8
quick_paths: ["ML_STATION_MAP", "STATE_SPACE_REASONING"]
tags: ["ml/architecture", "ssm", "mamba", "linear_attention", "priority/8"]
---

# 🐍 Mamba Selective State Space Model (SSM)

> **Station Origin:** `[[ML_STATION_MAP]]` (P10)  
> **Priority:** 8  
> **Direct Bridges:** `[[STATE_SPACE_REASONING]]` (P5)

---

## 🔬 Mathematical Formulation
Continuous selective state space recurrence from Gu & Dao:

$$\Delta = \text{softplus}(\delta_t)$$
$$\bar{A} = \exp(\Delta \cdot A_{\text{diag}})$$
$$\bar{B} = \Delta \cdot B_t$$
$$h_t = \bar{A} \cdot h_{t-1} + \bar{B} \cdot x_t$$
$$y_t = C_t^T \cdot h_t + D \cdot x_t$$

### Key Benefits for O0
- **Linear Inference Scaling:** $O(L)$ computational complexity with $O(1)$ state memory per token step.
- **Selective Memory Filtering:** $B_t$ and $C_t$ are input-dependent, allowing O0 to reset internal hidden state on topic switches.
- **Hardware Efficiency:** Fast parallel scan during training, recurrent step during auto-regressive generation.
