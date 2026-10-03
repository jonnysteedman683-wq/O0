"""THE FLYWHEEL: observe -> verify -> promote (v0, git-integrated).

At v0 O0 does not yet author its own code; it runs the promotion discipline:
observe its state, run every verification gate, measure the capability score,
and promote the result as a sha256-bound, append-only ledger record.

Git integration: a promotion becomes two SCOPED commits (never `git add -A`):
  1. source commit — the O0-owned dirty source (o0/, tests/, docs, skills/)
  2. ledger commit — state/ (ledger + memory) making the new record durable.

The ledger record references the source commit hash (written once, append-only).

This is the honest floor. Later tiers (v4/v5 in BLUEPRINT) push hypothesis
and implementation toward self-authorship while keeping this exact gate.
"""
from __future__ import annotations

from . import gitops
from .ledger import Ledger
from .nucleus import Nucleus
from .verify import capability_score, run_all_gates


class Flywheel:
    def __init__(self, ledger: Ledger | None = None, commit: bool = True):
        self.ledger = ledger or Ledger()
        self.nucleus = Nucleus(ledger=self.ledger)
        self.commit = commit

    def _constitution_satisfied(self, results) -> bool:
        for g in results:
            if g.name in ("gate.compile", "gate.harness", "gate.constitution"):
                if not g.passed:
                    return False
        ok, _checked, broken = self.ledger.verify_integrity()
        return ok and not broken

    def run_one(self) -> dict:
        observe = self.nucleus.observe()
        results = run_all_gates(self.ledger)
        score = capability_score(results)

        gates = [g.to_dict() for g in results]
        passed_all = self._constitution_satisfied(results)
        outcome = "promote" if passed_all else "reject"

        commits: dict = {}
        if outcome == "promote" and self.commit:
            # 1. Commit the O0-owned source first, so the ledger record can
            #    reference the source commit hash (append-only, written once).
            src_hash = gitops.commit(
                gitops.SOURCE_PATHS,
                f"O0 promote: source (gates {score['score']})",
            )
            commits["source_commit"] = src_hash

        ledger_rec = self.ledger.append(
            outcome,
            {
                "cycle": "v0-flywheel",
                "score": score["score"],
                "gates": gates,
                "commits": commits,
                "observations": {
                    "ledger_records": observe["ledger"]["records"],
                    "identity_constitution_sha256": observe["identity"]["constitution_sha256"],
                },
            },
        )

        if outcome == "promote" and self.commit:
            # 2. Commit the ledger so the new record is durable in git.
            ledger_hash = gitops.commit(
                gitops.STATE_PATHS,
                f"O0 promote seq={ledger_rec['seq']}: ledger (receipt {ledger_rec['receipt'][:8]})",
            )
            commits["ledger_commit"] = ledger_hash

        return {
            "outcome": outcome,
            "capability_score": score,
            "gates": gates,
            "commits": commits,
            "ledger_receipt": ledger_rec["receipt"],
            "ledger_seq": ledger_rec["seq"],
        }
