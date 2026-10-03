"""O0 CLI.

    python -m o0.main               run one flywheel iteration (observe->verify->promote)
    python -m o0.main --no-commit   run flywheel without git commits (dry run)
    python -m o0.main --ledger      verify sha256 integrity of every ledger record
    python -m o0.main --gates       run all verification gates and print capability score
    python -m o0.main --remember "text" [--tag t]   append an episodic memory
    python -m o0.main --recall "query"               keyword recall over episodic memory
    python -m o0.main --reason "shell task"          run the reasoning loop on a task
"""
from __future__ import annotations

import json
import sys

from .flywheel import Flywheel
from .ledger import Ledger
from .memory import Memory
from .reasoning import ReasoningLoop
from .verify import capability_score, run_all_gates


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    ledger = Ledger()
    memory = Memory()

    if "--remember" in argv:
        i = argv.index("--remember")
        if i + 1 >= len(argv):
            print("usage: --remember <text> [--tag t]")
            return 2
        text = argv[i + 1]
        tags = []
        if "--tag" in argv:
            j = argv.index("--tag")
            if j + 1 < len(argv):
                tags = [argv[j + 1]]
        rec = memory.remember("episodic", text, tags=tags)
        print(json.dumps(rec))
        return 0

    if "--recall" in argv:
        i = argv.index("--recall")
        if i + 1 >= len(argv):
            print("usage: --recall <query>")
            return 2
        hits = memory.recall(argv[i + 1])
        print(json.dumps(hits, indent=2))
        return 0

    if "--reason" in argv:
        i = argv.index("--reason")
        if i + 1 >= len(argv):
            print("usage: --reason <shell task>")
            return 2
        result = ReasoningLoop().run(argv[i + 1])
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1

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
    result = Flywheel(ledger=ledger, commit="--no-commit" not in argv).run_one()
    print(json.dumps(result, indent=2))
    return 0 if result["outcome"] == "promote" else 1


if __name__ == "__main__":
    sys.exit(main())
