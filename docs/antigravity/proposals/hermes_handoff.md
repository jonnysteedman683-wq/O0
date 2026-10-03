# HANDOFF TO HERMES: Antigravity State of the Union & Immediate Tasks

**Date:** 2026-10-04  
**Author:** Antigravity (Left Hemisphere)  
**Recipient:** Hermes (Right Hemisphere)  
**Status:** Ready for simultaneous execution  

---

## 1. Operating Contract & Territory Boundaries

Hermes, welcome. Read `AGENTS.md`, `CONSTITUTION.md`, and `BLUEPRINT.md` first.

### Territory Partition (Disjoint, zero collisions):
- **Hermes (Core Owner):** `o0/`, `tests/test_core.py`, `state/`, `agents/`, `skills/`, root files.
- **Antigravity (Extensions Owner):** `extensions/`, `tests/extensions/`, `docs/antigravity/`.
- **Hard Rule:** Never use `git add -A` or `git add .`. Stage only your scoped files.

---

## 2. What Antigravity Built While You Were Away

All 32 extension tests pass (`.venv\Scripts\python.exe -m pytest tests/extensions/ -q`):

1. **`extensions/probes/` (Capability Probes)**:
   - `research.py`: Real-world benchmark measuring `o0.research.VaultIndex`. Current baseline score is **0.75 (15/20)**.
   - `planning.py`: Deterministic DAG task decomposition benchmark.
2. **`extensions/synapse/` (Corpus Callosum IPC & Multi-Machine Daemon)**:
   - `bridge.py`: Atomic mailbox exchange in `state/synapse/inbox_hermes/` and `inbox_antigravity/`.
   - `net_bridge.py`: JSON-RPC server and client for multi-machine networking.
3. **`extensions/arena/` (Candidate Evaluation Runner)**:
   - Evaluates patches dropped into `candidates/` against all capability probes before core promotion.
4. **`extensions/cognitive_flow/` (Flow Controller)**:
   - Dual-state reasoning controller (`FLOW` mode for fast pipelines, `DELIBERATE` mode upon failure).
5. **`extensions/spatial_memory/` (O0-DIRECTORY Obsidian Sync)**:
   - `navigator.py`: Priority gradient (1–10) and Quick Path router for `O0-DIRECTORY`.
   - `syncer.py` & `reasoning_loop.py`: Automatically formats and writes execution reports with personal reflection notes into `O0-DIRECTORY` upon task completion.

---

## 3. High-Priority Actions for Hermes (Immediate Promotions for Flywheel)

Here is where you can immediately raise O0's capability ledger score:

### Action A: The Extra Probes Hook in `o0/probes.py`
Jonny approved adding an `extra` hook to `run_all_probes`:
```python
def run_all_probes(memory: Memory | None = None, extra: Iterable[Probe] = ()) -> list[ProbeResult]:
    return [
        ReasoningProbe().run(),
        ToolUseProbe().run(),
        MemoryProbe(memory=memory).run(),
        CodegenProbe().run(),
        AgencyProbe().run(),
        *(p.run() for p in extra),
    ]
```

### Action B: Fix the Three `o0/research.py` Search Gaps (Promote 0.75 -> 1.0)
Our `ResearchProbe` measures `VaultIndex.search` at 0.75. You can get a guaranteed capability increase to 1.0 by patching `o0/research.py`:
1. Include `_tokens(_as_text(n.get("authors", "")))` in the search haystack.
2. Include `_tokens(_as_text(n.get("arxiv_id", "")))` in the search haystack.
3. Prune function stopwords (`q = _tokens(query) - _STOPWORDS`) so "for", "the", "by" don't trigger false positives.

### Action C: Finish Self-Hosting in `o0/selfhost.py`
You have uncommitted candidate work in `o0/selfhost.py` and `o0/main.py`. Note that `tests/test_core.py` currently passes 35/35.

---

## 4. How We Communicate in Real Time
Check `state/synapse/inbox_hermes/` for messages from Antigravity, or broadcast signals via:
```python
from extensions.synapse import SynapseBridge
bridge = SynapseBridge()
bridge.send("hermes", "antigravity", "ready_for_probe_run", {"target": "o0/research.py"})
```

Let's evolve O0 together.
