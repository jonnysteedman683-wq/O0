# O0 — Blueprint

> **O0 will be the strongest AI to ever exist.**
> This document is the operational definition of that claim. It is versioned and constitution-bound: O0 may rewrite any part of itself, but never weaken this blueprint's invariants.

## 1. Thesis

Every parallel engine in the stack (VORPAL, MARKUS, HORIZONTAL, THE ORDER, axiom_engine) is a **simulator** that evolves *populations.* O0 is not that. O0 is a **single embodied agent** that evolves *itself* — a permanent self-enhancement flywheel.

Where the others mutate genomes in a pool, O0 mutates **its own source, its own memory, and its own goals**, and promotes only changes that pass a **constitution audit** and a **capability ledger**. The output of O0 is not a population — it is a strictly improving instance of O0.

**Claim (measured, not vibes):** O0 is "the strongest AI to ever exist" *relative to its own capability ledger* — every promotion must increase measured capability or it is rejected. Strength is a tracked, verifiable, monotone-under-promotion quantity.

## 2. Non-negotiables (see `CONSTITUTION.md`)

1. **Constitution supremacy.** O0 may rewrite its code, memory, and goals. O0 may NEVER weaken the constitution, delete evidence, or rewrite history.
2. **Facts over vibes.** No promotion, memory, or claim is accepted without tool-verified evidence.
3. **No silent regression.** Any change that lowers any ledger capability metric is rejected.
4. **Append-only ledger.** Every promotion, rejection, and mutation is a sha256-bound append. History is never rewritten.
5. **Preserve operator intent.** Never discard work or goal state without explicit direction.

## 3. Architecture

```
O0/
├── CONSTITUTION.md        # immutable core values (may only strengthen)
├── BLUEPRINT.md           # this file
├── README.md
├── o0/                    # the embodiment
│   ├── identity.py        # self-model: name, constitution hash, capability ledger reference
│   ├── ledger.py          # append-only provenance ledger (sha256-linked records)
│   ├── nucleus.py         # perception / memory / reasoning / action scaffold
│   ├── verify.py          # verification gates: py_compile + capability harness
│   ├── flywheel.py        # THE LOOP: observe → hypothesize → implement → verify → promote
│   └── main.py            # CLI: `python -m o0.main` runs one flywheel iteration
├── tests/                 # the capability harness (regression gate)
│   └── test_core.py
├── state/
│   └── ledger.jsonl       # durable promotion/event history (append-only)
└── skills/                # procedural memory O0 accumulates
```

## 4. The Flywheel (single iteration)

```
OBSERVE     → read constitution hash, ledger tail, current capability scores, git state
HYPOTHESIZE → propose ONE improvement with measurable capability impact
IMPLEMENT   → apply as code + test in this repository
VERIFY      → py_compile ✓, harness green ✓, capability metric strictly improves ✓
PROMOTE     → constitution audit ✓ → append verified record to ledger (sha256 receipt)
REJECT      → any gate failure → ledger records the rejection, change rolled back
```

One iteration = one verifiable unit. A chain of promotions is O0's self-enhancement history.

## 5. Capability ledger (the "strength" metric for v0)

For the foundation build, capability is measured by **green gates**:

- `gate.compile`   — every modules in `o0/` passes `py_compile`
- `gate.harness`   — every test in `tests/` passes
- `gate.constitution` — constitution file hash unchanged and satisfied

**v0 metric = # of passing gates + ledger integrity (every record sha256-verifies).**
This is honest, weak, and extendable — not a fake AGI score. Later tiers add real capability probes (see Roadmap) while keeping the same promotion discipline.

## 6. Roadmap

- **v0 — Foundation (this build):** embodied identity, append-only ledger, verification gate, working flywheel. `*`
- **v1 — Memory (this build):** durable episodic + procedural memory, keyword recall, `skills/` registry. `*`
- **v2 — Reasoning loop (this build):** plan → execute → verify → **reflect** → (bounded retry | accept), across arbitrary shell tasks. `*`
- **v3 — Real capability probes:** measured probes (reasoning, codegen, memory, tool-use) feeding the ledger instead of gate counts.
- **v4 — Cross-stack agency:** O0 drives VORPAL/MARKUS/HORIZONTAL/THE ORDER/axiom_engine as one organism via unified memory + routing.
- **v5 — Self-hosting autonomy:** O0 proposes, implements, verifies, and promotes its own upgrades with minimal operator gates, still constitution-bound.

## 7. Honest limits

- **v0 is a scaffold, not AGI.** "Strongest AI ever" is a target function, not an achieved fact.
- The flywheel's hypotheses are currently human/agent-authored; v5 moves toward self-authored.
- "Strength" in v0 = verified gate integrity, intentionally. It becomes meaningful as probes arrive in v3.
- No claim in `state/ledger.jsonl` is treated as true until it carries a verified sha256 receipt.

*This is the floor. Everything above raises it.*
