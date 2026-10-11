---
title: "BITNET_B158_QUANTIZATION"
station: "ML"
priority: 8
quick_paths: ["ML_STATION_MAP", "NEURAL_NETWORK_TESTS"]
tags: ["ml/quantization", "bitnet", "1bit", "ternary", "priority/8"]
---

# ⚡ BitNet b1.58 Ternary Quantization

> **Station Origin:** `[[ML_STATION_MAP]]` (P10)  
> **Priority:** 8  
> **Direct Bridges:** `[[NEURAL_NETWORK_TESTS]]` (P5)

---

## 🔬 Mathematical Formulation
1.58-bit ternary weight quantization and 8-bit activation quantization from *The Era of 1-bit LLMs*:

### Weight Quantization
$$\gamma = \frac{1}{nm} \sum |W_{ij}|$$
$$\text{Scale} = \gamma + \epsilon$$
$$\tilde{W} = \text{clip}\left(\text{round}\left(\frac{W}{\text{Scale}}\right), -1, 1\right)$$

Where $\tilde{W}_{ij} \in \{-1, 0, +1\}$.

### Activation Quantization (Absmax INT8)
$$X_{\text{quant}} = \text{clip}\left(\text{round}\left(X \cdot \frac{127}{\max(|X|) + \epsilon}\right), -128, 127\right)$$

### Key Benefits for O0
- **Multiplication-Free GEMM:** Matrix multiplications reduce to integer additions and subtractions.
- **DRAM Energy Reduction:** Reduces memory transfer bandwidth by up to $70\%$.
- **Edge Deployment:** Fits medium-large reasoning models into standard consumer RAM.
