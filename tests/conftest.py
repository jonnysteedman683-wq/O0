"""Keep the whole test suite out of Hermes's durable records (AGENTS.md rule 7).

``Ledger``, ``Memory`` and ``VaultIndex`` bind their default paths
(``state/ledger.jsonl``, ``state/memory.jsonl``, ``state/vault_index.json``) at
definition time. Any test that builds one indirectly (probes, orchestrator,
agency probe) would otherwise append to the real files. This fixture swaps those
defaults for per-test temp paths. Explicitly passed paths are untouched.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from o0.ledger import Ledger
from o0.memory import Memory
from o0.research import VaultIndex


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path_factory: pytest.TempPathFactory,
                   monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    state: Path = tmp_path_factory.mktemp("state")
    monkeypatch.setattr(Ledger.__init__, "__defaults__", (state / "ledger.jsonl",))
    mem_defaults = Memory.__init__.__defaults__ or ()
    monkeypatch.setattr(Memory.__init__, "__defaults__",
                        (state / "memory.jsonl", *mem_defaults[1:]))
    vi_defaults = VaultIndex.__init__.__defaults__ or ()
    monkeypatch.setattr(VaultIndex.__init__, "__defaults__",
                        (*vi_defaults[:-1], state / "vault_index.json"))
    yield
