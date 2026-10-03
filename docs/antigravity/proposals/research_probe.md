# Proposal: research probe → core ledger, and three VaultIndex.search fixes

**From:** Antigravity · **To:** Hermes / Jonny · **Status:** proposal (no core edits made)

## 1. What exists now (extensions territory)

`extensions/probes/research.py` — `ResearchProbe` (`name = "research"`), a
`o0.probes.Probe` subclass. It writes a bundled, fixed 12-note corpus into a
temp dir, indexes it with the real `o0.research.VaultIndex`, and runs 20
fixed queries through `VaultIndex.search()`. It never touches
`state/vault_index.json`.

Measured baseline (deterministic, reproduced across runs):

```
research: score 0.75 (15/20)
  content 12/12 · metadata 1/4 · negative 2/4
  positives hit@3 13/16 · MRR@5 0.812
```

## 2. Proposal A — wire the probe into the core ledger (needs Hermes)

Add to `o0/probes.py::run_all_probes()` (or the flywheel's probe list):

```python
from extensions.probes import run_extension_probes
...
return [ ...core probes..., *run_extension_probes() ]
```

Open question for Hermes: should `o0/` import from `extensions/`, or would
you prefer a plugin hook (e.g. `run_all_probes(extra=[...])`) so the core
stays independent of extensions? I'd recommend the hook. Note the
no-silent-regression rule: once "research" is in the ledger at 0.75, any
search change that drops it gets rejected — that is the intent.

## 3. Proposal B — three real search gaps the probe exposes

All in `o0/research.py::VaultIndex.search` (core — not touched by me):

| Failing task | Cause | Suggested fix |
|---|---|---|
| `papers by Goodfellow` → batchnorm, ddpm | `authors` is indexed but not searched; `by` matches body text | include `authors` tokens in the haystack |
| `arxiv 1512.03385`, `1810.04805` → no hits | `arxiv_id` indexed but not searched | include `arxiv_id` (raw string + tokens) in the haystack |
| `recipes for sourdough bread`, `the history of the roman empire` → false hits | no stopword filtering; `for`/`the`/`of` give score ≥ 1 | drop a small stopword set from query tokens |

Fixing all three should move the probe to 20/20 = 1.0 — a clean,
measurable promotion for the flywheel. After that, I'd add harder tasks
(synonyms, paraphrase) to keep headroom.

## 4. Housekeeping I did inside my territory (FYI)

I deleted `tests/extensions/__init__.py`. Because there's no `tests/__init__.py`,
pytest (rootdir/prepend import mode) was importing `tests/extensions/` as a
top-level package named `extensions`. That hid the real `extensions/`
package, so collection failed with `ModuleNotFoundError: extensions.probes`.
Your `pytest tests/` run would have hit the same error. With the file gone,
`pytest tests/ --collect-only` collects all 41 tests.
Rule going forward: test files under `tests/extensions/` need unique
basenames (no `test_core.py` there).

## 5. Environment note

The system `python` (3.14) has no pytest. I ran everything with
`.venv\Scripts\python.exe`. If AGENTS.md is meant to say plain `python`, it
should probably name the venv explicitly.
