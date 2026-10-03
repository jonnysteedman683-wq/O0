"""O0 CLI.

    python -m o0.main               run one flywheel iteration (observe->verify->promote)
    python -m o0.main --ledger      verify sha256 integrity of every ledger record
    python -m o0.main --gates       run all verification gates and print capability score
"""
from __future__ import annotations

import json
import sys

from .flywheel import Flywheel
from .ledger import Ledger
from .verify import capability_score, run_all_gates


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    ledger = Ledger()

    if "--ledger" in argv:
        ok, checked, broken = ledger.verify_integrity()
        print(f"ledger: {checked} records, integrity_ok={ok}")
        if broken:
            print("broken receipts:", broken)
            return 1
        return 0

    if "--gates" in argv:
        results = run_all_gates(ledger)
        score = capability_score(results)
        for g in results:
            print(f"  [{'x' if g.passed else '!'}] {g.name}: {g.detail}")
        print("score:", json.dumps(score))
        return 0

    # default: run the flywheel
    result = Flywheel(ledger=ledger).run_one()
    print(json.dumps(result, indent=2))
    return 0 if result["outcome"] == "promote" else 1


if __name__ == "__main__":
    sys.exit(main())
