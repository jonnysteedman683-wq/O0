"""O0 CLI.

    python -m o0.main               run one flywheel iteration (observe->verify->promote)
    python -m o0.main --no-commit   run flywheel without git commits (dry run)
    python -m o0.main --ledger      verify sha256 integrity of every ledger record
    python -m o0.main --gates       run all verification gates and print capability score
    python -m o0.main --probes      run capability probes and print measured scores
    python -m o0.main --remember "text" [--tag t]   append an episodic memory
    python -m o0.main --recall "query"               keyword recall over episodic memory
    python -m o0.main --reason "shell task"          run the reasoning loop on a task
    python -m o0.main --index-vault [path]           index the Obsidian vault (default: HORIZONTAL ML dossiers)
    python -m o0.main --research "query"             search the vault index for ML research
    python -m o0.main --topics                        show vault index topic aggregates
    python -m o0.main --create-agent <name> <role>   create a new agent (O0 creates AIs)
    python -m o0.main --dispatch <agent> <task>      dispatch a task to a created agent
    python -m o0.main --stack                        probe cross-stack platform availability
"""
from __future__ import annotations

import json
import sys

from .agency import AgentSpec, Orchestrator
from .flywheel import Flywheel
from .ledger import Ledger
from .memory import Memory
from .probes import run_all_probes
from .reasoning import ReasoningLoop
from .research import DEFAULT_ML_DIR, VaultIndex
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

    if "--create-agent" in argv:
        i = argv.index("--create-agent")
        if i + 2 >= len(argv):
            print("usage: --create-agent <name> <role>")
            return 2
        orch = Orchestrator(ledger=ledger)
        agent = orch.create_agent(AgentSpec(name=argv[i + 1], role=argv[i + 2]))
        print(json.dumps({"created": agent.name, "path": str(agent.module_path)}))
        return 0

    if "--dispatch" in argv:
        i = argv.index("--dispatch")
        if i + 2 >= len(argv):
            print("usage: --dispatch <agent> <task>")
            return 2
        orch = Orchestrator(ledger=ledger)
        res = orch.dispatch(argv[i + 1], argv[i + 2])
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1

    if "--stack" in argv:
        orch = Orchestrator(ledger=ledger)
        print(json.dumps(orch.stack_status(), indent=2))
        return 0

    if "--index-vault" in argv:
        i = argv.index("--index-vault")
        path = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else DEFAULT_ML_DIR
        idx = VaultIndex(vault_path=path)
        stats = idx.index()
        print(json.dumps(stats, indent=2))
        return 0

    if "--research" in argv:
        i = argv.index("--research")
        if i + 1 >= len(argv):
            print("usage: --research <query>")
            return 2
        idx = VaultIndex()
        if not idx.load():
            print("index not built yet; run --index-vault first", file=sys.stderr)
            return 2
        hits = idx.search(argv[i + 1])
        print(json.dumps(hits, indent=2))
        return 0

    if "--topics" in argv:
        idx = VaultIndex()
        if not idx.load():
            print("index not built yet; run --index-vault first", file=sys.stderr)
            return 2
        print(json.dumps(idx.topics(), indent=2))
        return 0

    if "--probes" in argv:
        probes = [p.to_dict() for p in run_all_probes(memory=memory)]
        print(json.dumps(probes, indent=2))
        return 0

    if "--ledger" in argv:
        ok, checked, broken = ledger.verify_integrity()
        print(f"ledger: {checked} records, integrity_ok={ok}")
        if broken:
            print("broken receipts:", broken)
            return 1
        return 0

    if "--gates" in argv:
        results = run_all_gates(ledger)
        score = capability_score(results, memory=memory)
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
