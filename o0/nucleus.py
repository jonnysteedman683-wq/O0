"""Perception / memory / reasoning / action — the embodied scaffolding.

At v0 the nucleus is a thin, honest layer: it observes identity + ledger
state and exposes a capability report. Later tiers (v1 memory, v2 reasoning,
v3 real probes) deepen this without changing its contract.
"""
from __future__ import annotations

from .identity import Identity
from .ledger import Ledger


class Nucleus:
    """O0's inner loop contract: OBSERVE -> report capabilities."""

    def __init__(self, ledger: Ledger | None = None):
        self.identity = Identity()
        self.ledger = ledger or Ledger()

    def observe(self) -> dict:
        """Return a verifiable snapshot of O0's current state."""
        ok, checked, broken = self.ledger.verify_integrity()
        records = self.ledger.read()
        return {
            "identity": self.identity.manifest(),
            "ledger": {
                "path": str(self.ledger.path),
                "records": len(records),
                "integrity_ok": ok,
                "broken_receipts": broken,
                "gates_checked": checked,
                "tail": self.ledger.tail(3),
            },
        }
