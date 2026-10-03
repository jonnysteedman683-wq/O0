"""O0 research probe (extension): measured retrieval quality of o0.research.

Mirrors o0/probes.py: a `Probe` subclass running a FIXED, deterministic task
suite and returning a 0.0-1.0 `ProbeResult`.

What it measures
----------------
The real `o0.research.VaultIndex` (index + search), end to end:

  1. A bundled, fixed corpus of ML-dossier-style notes (YAML frontmatter +
     body, same shape as the HORIZONTAL vault) is written into a fresh
     temporary directory.
  2. `VaultIndex.index()` parses it. The index file is written to the temp
     dir too — the probe NEVER touches `state/vault_index.json`.
  3. A fixed query suite is run through `VaultIndex.search()`:
       - positive queries: natural-language questions with exactly one gold
         note; PASS iff the gold note is ranked #1.
       - negative controls: off-topic queries; PASS iff search returns
         nothing (precision / no false recall).

score = passed / total (same convention as the core probes). The detail
string additionally reports MRR@5 and hit@3 over the positive queries, so
partial retrieval quality is visible even when top-1 misses.

Why a bundled corpus rather than the live vault: the live vault changes over
time, which would make scores incomparable across runs. A fixed corpus makes
this a real capability probe — the score only moves when O0's search code
changes. Nothing here is tuned to make the search look good or bad; queries
are phrased the way a researcher would ask.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from o0.probes import Probe, ProbeResult
from o0.research import VaultIndex

# -- fixed corpus ----------------------------------------------------------
# filename -> markdown (frontmatter + body). Shape matches the vault dossiers.
CORPUS: dict[str, str] = {
    "attention.md": """---
title: "Attention Is All You Need"
category: architecture
authors: [Vaswani, Shazeer, Parmar]
algo_focus: transformer
arxiv_id: "1706.03762"
tags: [transformer, attention, nlp]
---
The Transformer is a sequence transduction architecture based solely on
self-attention, dispensing with recurrence and convolutions entirely.
It achieves state-of-the-art BLEU on WMT English-German machine translation
while being more parallelizable and faster to train.
""",
    "resnet.md": """---
title: "Deep Residual Learning for Image Recognition"
category: vision
authors: [He, Zhang, Ren, Sun]
algo_focus: cnn
arxiv_id: "1512.03385"
tags: [cnn, vision, residual]
---
Residual networks reformulate layers as learning residual functions with
reference to the layer inputs, using identity shortcut connections. This
eases optimization of very deep convolutional networks (152 layers) and won
the ImageNet 2015 classification challenge.
""",
    "adam.md": """---
title: "Adam: A Method for Stochastic Optimization"
category: optimization
authors: [Kingma, Ba]
algo_focus: optimizer
arxiv_id: "1412.6980"
tags: [optimizer, sgd]
---
Adam is a first-order gradient-based optimizer using adaptive estimates of
lower-order moments. It computes individual adaptive learning rates for
each parameter from estimates of the first and second moments of the
gradients, and is robust to noisy and sparse gradients.
""",
    "dropout.md": """---
title: "Dropout: A Simple Way to Prevent Neural Networks from Overfitting"
category: regularization
authors: [Srivastava, Hinton, Krizhevsky]
algo_focus: regularization
tags: [regularization, overfitting]
---
Dropout randomly drops units, along with their connections, from the neural
network during training. This prevents units from co-adapting too much and
significantly reduces overfitting, acting like an ensemble of many thinned
networks.
""",
    "batchnorm.md": """---
title: "Batch Normalization: Accelerating Deep Network Training"
category: optimization
authors: [Ioffe, Szegedy]
algo_focus: normalization
arxiv_id: "1502.03167"
tags: [normalization, training]
---
Training is complicated by internal covariate shift: the distribution of
each layer's inputs changes as earlier parameters change. Batch
normalization normalizes layer inputs over each mini-batch, allowing much
higher learning rates and less careful initialization.
""",
    "ppo.md": """---
title: "Proximal Policy Optimization Algorithms"
category: reinforcement_learning
authors: [Schulman, Wolski, Dhariwal]
algo_focus: policy_gradient
arxiv_id: "1707.06347"
tags: [rl, policy_gradient]
---
PPO is a family of policy gradient methods for reinforcement learning that
alternate between sampling data from the environment and optimizing a
clipped surrogate objective with stochastic gradient ascent, giving the
stability of trust-region methods with a simpler implementation.
""",
    "dqn.md": """---
title: "Human-level Control through Deep Reinforcement Learning"
category: reinforcement_learning
authors: [Mnih, Kavukcuoglu, Silver]
algo_focus: value_based
tags: [rl, q_learning, atari]
---
The deep Q-network (DQN) learns control policies directly from raw pixels
using Q-learning with a convolutional network. Experience replay and a
target network stabilize training; the agent reaches human-level play on
49 Atari 2600 games.
""",
    "gan.md": """---
title: "Generative Adversarial Networks"
category: generative
authors: [Goodfellow, Bengio]
algo_focus: gan
arxiv_id: "1406.2661"
tags: [generative, adversarial]
---
A generative model G and a discriminative model D are trained
simultaneously in a two-player minimax game: the generator learns to
produce samples that the discriminator cannot distinguish from real data.
""",
    "vae.md": """---
title: "Auto-Encoding Variational Bayes"
category: generative
authors: [Kingma, Welling]
algo_focus: vae
arxiv_id: "1312.6114"
tags: [generative, variational]
---
A stochastic variational inference and learning algorithm for directed
probabilistic models with continuous latent variables. The
reparameterization trick yields a lower-bound estimator that can be
optimized with standard stochastic gradient methods.
""",
    "lora.md": """---
title: "LoRA: Low-Rank Adaptation of Large Language Models"
category: nlp
authors: [Hu, Shen, Wallis]
algo_focus: fine_tuning
arxiv_id: "2106.09685"
tags: [llm, fine_tuning, peft]
---
LoRA freezes the pretrained model weights and injects trainable low-rank
decomposition matrices into each Transformer layer, greatly reducing the
number of trainable parameters for downstream adaptation of large language
models.
""",
    "bert.md": """---
title: "BERT: Pre-training of Deep Bidirectional Transformers"
category: nlp
authors: [Devlin, Chang, Lee, Toutanova]
algo_focus: transformer
arxiv_id: "1810.04805"
tags: [nlp, pretraining, transformer]
---
BERT pretrains deep bidirectional representations from unlabeled text using
a masked language model objective and next-sentence prediction. The
pretrained model is fine-tuned with one additional output layer for
question answering and language inference.
""",
    "ddpm.md": """---
title: "Denoising Diffusion Probabilistic Models"
category: generative
authors: [Ho, Jain, Abbeel]
algo_focus: diffusion
arxiv_id: "2006.11239"
tags: [generative, diffusion]
---
High quality image synthesis using diffusion probabilistic models, a class
of latent variable models trained to reverse a gradual noising process.
Samples are generated by iterative denoising, achieving a state-of-the-art
FID on CIFAR10.
""",
}


@dataclass(frozen=True)
class ResearchTask:
    query: str
    gold: str | None  # corpus filename expected at rank 1; None = expect no hits
    kind: str = "content"  # content | metadata | negative


# -- fixed query suite -----------------------------------------------------
RESEARCH_TASKS: list[ResearchTask] = [
    ResearchTask("self-attention model for machine translation", "attention.md"),
    ResearchTask("shortcut connections for training very deep networks", "resnet.md"),
    ResearchTask("optimizer with adaptive learning rates per parameter", "adam.md"),
    ResearchTask("how to prevent overfitting in neural networks", "dropout.md"),
    ResearchTask("reducing internal covariate shift", "batchnorm.md"),
    ResearchTask("clipped surrogate objective", "ppo.md"),
    ResearchTask("playing Atari games from pixels", "dqn.md"),
    ResearchTask("generator versus discriminator minimax game", "gan.md"),
    ResearchTask("reparameterization trick for latent variables", "vae.md"),
    ResearchTask("parameter-efficient fine-tuning of large language models", "lora.md"),
    ResearchTask("masked language model pretraining", "bert.md"),
    ResearchTask("image synthesis by iterative denoising", "ddpm.md"),
    # metadata lookups: a researcher often knows the author or arXiv id.
    # VaultIndex stores `authors` and `arxiv_id`; these check they are findable.
    ResearchTask("papers by Goodfellow", "gan.md", "metadata"),
    ResearchTask("Schulman policy optimization paper", "ppo.md", "metadata"),
    ResearchTask("arxiv 1512.03385", "resnet.md", "metadata"),
    ResearchTask("1810.04805", "bert.md", "metadata"),
    # negative controls: nothing in the corpus is about these -> expect no hits
    ResearchTask("quantum chromodynamics lattice", None, "negative"),
    ResearchTask("medieval french poetry", None, "negative"),
    ResearchTask("recipes for sourdough bread", None, "negative"),
    ResearchTask("the history of the roman empire", None, "negative"),
]

TOP_K = 5
KINDS = ("content", "metadata", "negative")


class ResearchProbe(Probe):
    """Retrieval quality of o0.research.VaultIndex on a fixed corpus + query set."""

    name = "research"

    def __init__(self, corpus: dict[str, str] | None = None,
                 tasks: list[ResearchTask] | None = None):
        self.corpus = CORPUS if corpus is None else corpus
        self.tasks = RESEARCH_TASKS if tasks is None else tasks
        # per-task outcomes from the most recent run (for inspection/debugging)
        self.last_results: list[dict] = []

    def run(self) -> ProbeResult:
        self.last_results = []
        if not self.tasks:
            return ProbeResult(self.name, None, 0, 0, "not measured: empty task suite")
        try:
            with tempfile.TemporaryDirectory(prefix="o0_research_probe_") as tmp:
                root = Path(tmp)
                vault = root / "vault"
                vault.mkdir()
                for fname, text in self.corpus.items():
                    (vault / fname).write_text(text, encoding="utf-8")
                idx = VaultIndex(vault_path=vault, index_path=root / "index.json")
                idx.index()
                return self._score(idx)
        except Exception as exc:  # honest failure, never a fabricated score
            self.last_results = []
            return ProbeResult(self.name, 0.0, 0, len(self.tasks),
                               f"research probe error: {type(exc).__name__}: {exc}")

    def _score(self, idx: VaultIndex) -> ProbeResult:
        rr_sum = 0.0
        hit3 = 0
        n_pos = 0
        for task in self.tasks:
            hits = idx.search(task.query, limit=TOP_K)
            ranked = [Path(h["rel"]).name for h in hits]
            rank = None
            if task.gold is None:
                ok = not ranked
            else:
                n_pos += 1
                rank = ranked.index(task.gold) + 1 if task.gold in ranked else None
                ok = rank == 1
                if rank is not None:
                    rr_sum += 1.0 / rank
                    hit3 += int(rank <= 3)
            self.last_results.append({"query": task.query, "gold": task.gold,
                                      "kind": task.kind, "ranked": ranked,
                                      "rank": rank, "passed": ok})
        total = len(self.tasks)
        passed = sum(1 for r in self.last_results if r["passed"])
        parts = []
        for kind in KINDS:
            rows = [r for r in self.last_results if r["kind"] == kind]
            if rows:
                parts.append(f"{kind} {sum(r['passed'] for r in rows)}/{len(rows)}")
        mrr = rr_sum / n_pos if n_pos else 0.0
        detail = (f"{passed}/{total} retrieval tasks correct ({', '.join(parts)}; "
                  f"positives hit@3 {hit3}/{n_pos}, MRR@{TOP_K} {mrr:.3f})")
        return ProbeResult(self.name, passed / total, passed, total, detail)
