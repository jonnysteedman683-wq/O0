"""THE FLYWHEEL: observe -> verify -> promote (v0).

At v0 O0 does not yet author its own code; it runs the promotion discipline:
observe its state, run every verification gate, measure the capability score,
and promote the result as a sha256-bound, append-only ledger record.

This is the honest floor. Later tiers (v4/v5 in BLUEPRINT) push hypothesis
and implementation toward self-authorship while keeping this exact gate.
"""
from __future__ import annotations

from .identity import Identity
from .ledger import Ledger
from .nucleus import Nucleus
from .verify import capability_score, run_all_gates


class Flywheel:
    def __init__(self, ledger: Ledger | None = None):
        self.ledger = ledger or Ledger()
        self.nucleus = Nucleus(ledger=self.ledger)

    def run_one(self) -> dict:
        def _constitution_satisfied(results, obs) -> bool:
            # No gate may fail the constitution; harness+compile must be green.
            for g in results:
                if g.name in ("gate.compile", "gate.harness", "gate.constitution"):
                    if not g.passed:
                        return False
            # Ledger must not be broken.
            ok, _checked, broken = self.ledger.verify_integrity()
            return ok and not broken

        observe = self.nucleus.observe()
        results = run_all_gates(self.ledger)
        score = capability_score(results)

        gates = [g.to_dict() for g in results]
        passed_all = _constitution_satisfied(results, observe)
        outcome = "promote" if passed_all else "reject"

        ledger_rec = self.ledger.append(
            outcome,
            {
                "cycle": "v0-flywheel",
                "score": score["score"],
                "gates": gates,
                "observations": {
                    "ledger_records": observe["ledger"]["records"],
                    "identity_constitution_sha256": observe["identity"]["constitution_sha256"],
                },
            },
        )
        return {
            "outcome": outcome,
            "capability_score": score,
            "gates": gates,
            "ledger_receipt": ledger_rec["receipt"],
            "ledger_seq": ledger_rec["seq"],
        }
