"""Guard for AGENTS.md rule 7: the extensions suite must never write into Hermes territory.

Snapshots ``state/`` and the ``O0-DIRECTORY`` vault before the session and fails the run if any
file was added, removed, or modified. A test that needs a vault or memory store must use
``tmp_path`` (see ``test_cluster.py`` / ``test_vault_syncer.py``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARDED = (REPO_ROOT / "state", REPO_ROOT / "O0-DIRECTORY")


def _snapshot() -> dict[str, str]:
    snap: dict[str, str] = {}
    for root in GUARDED:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file():
                snap[str(p.relative_to(REPO_ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return snap


@pytest.fixture(scope="session", autouse=True)
def _protect_hermes_territory() -> Iterator[None]:
    before = _snapshot()
    yield
    after = _snapshot()
    changed = sorted(
        k for k in before.keys() | after.keys() if before.get(k) != after.get(k)
    )
    if changed:
        pytest.fail(
            "extensions tests modified Hermes territory (AGENTS.md rule 7): "
            + ", ".join(changed[:10])
            + (" ..." if len(changed) > 10 else ""),
            pytrace=False,
        )
