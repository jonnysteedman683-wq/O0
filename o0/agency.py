"""O0 cross-stack agency (v4): O0 CREATES AIs and controls them.

The unique capability: O0 does not merely coordinate the stack — it can
materialize a NEW agent (identity + constitution + runnable module), register
it in the ledger, dispatch tasks to it, and probe the whole stack.

Components:
  - AgentSpec / AgentFactory : define + materialize a new agent as a real
    runnable Python module under agents/ (this is "O0 creates AIs").
  - Agent / AgentRegistry    : load and run created agents.
  - Connector / StackConnector: pluggable adapters to VORPAL, MARKUS-OS,
    HORIZONTAL, THE ORDER, axiom_engine. At v4 these are honest availability
    probes (fail-open, like the markus_vorpal_bridge pattern) — cross-stack
    execution is v5.
  - Orchestrator             : create agents, dispatch tasks, report stack.

Every created agent is registered in the append-only ledger with a sha256 of
its generated code, so agent creation is auditable and durable.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .ledger import Ledger

REPO_ROOT = Path(os.path.dirname(os.path.abspath(__file__))).parent
AGENTS_DIR = REPO_ROOT / "agents"

# Stack roots (fail-open: a missing root just reports unreachable).
STACK_ROOTS: dict[str, str] = {
    "VORPAL": "C:/Users/jonny/OneDrive/Desktop/VORPAL",
    "MARKUS": "C:/Users/jonny/OneDrive/Desktop/MARKUS-OS",
    "HORIZONTAL": "C:/Users/jonny/OneDrive/Desktop/HORIZONTAL",
    "THE_ORDER": "C:/Users/jonny/OneDrive/Desktop/THE ORDER",
    "AXIOM_ENGINE": "C:/Users/jonny/OneDrive/Desktop/axiom_engine",
}

AGENT_TEMPLATE = '''\
"""Agent {name} — created by O0 (v4 cross-stack agency)."""
from o0.reasoning import ReasoningLoop

ROLE = {role!r}
CONSTITUTION = {constitution!r}

def run(task: str) -> dict:
    """Execute a task through O0's reasoning loop."""
    return ReasoningLoop().run(task)
'''


@dataclass
class AgentSpec:
    name: str
    role: str
    constitution: str = "Serve O0's goals; never weaken the O0 constitution."
    capabilities: list[str] = field(default_factory=list)


class Agent:
    """A created agent: a runnable module O0 can dispatch tasks to."""

    def __init__(self, name: str, module_path: Path):
        self.name = name
        self.module_path = module_path

    def run(self, task: str) -> dict:
        spec = importlib.util.spec_from_file_location(
            f"o0_agent_{self.name}", self.module_path)
        if spec is None or spec.loader is None:
            return {"agent": self.name, "ok": False, "detail": "module load failed"}
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return {"agent": self.name, "ok": True, "result": mod.run(task)}


class AgentFactory:
    """Materializes a new agent as a real module and registers it."""

    def __init__(self, ledger: Ledger | None = None, agents_dir: Path | str = AGENTS_DIR):
        self.ledger = ledger or Ledger()
        self.agents_dir = Path(agents_dir)

    def create(self, spec: AgentSpec) -> Agent:
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        code = AGENT_TEMPLATE.format(name=spec.name, role=spec.role,
                                     constitution=spec.constitution)
        path = self.agents_dir / f"{spec.name}.py"
        path.write_text(code, encoding="utf-8")
        code_sha = hashlib.sha256(code.encode("utf-8")).hexdigest()
        self.ledger.append("agent_created", {
            "agent": spec.name,
            "role": spec.role,
            "path": str(path),
            "code_sha256": code_sha,
            "capabilities": spec.capabilities,
        })
        return Agent(spec.name, path)


class AgentRegistry:
    def __init__(self, agents_dir: Path | str = AGENTS_DIR):
        self.agents_dir = Path(agents_dir)

    def list(self) -> list[dict]:
        if not self.agents_dir.exists():
            return []
        return [{"name": p.stem, "path": str(p)}
                for p in sorted(self.agents_dir.glob("*.py"))]

    def load(self, name: str) -> Agent | None:
        path = self.agents_dir / f"{name}.py"
        if not path.exists():
            return None
        return Agent(name, path)


class Connector:
    name = "connector"

    def status(self) -> dict:
        raise NotImplementedError

    def dispatch(self, task: str) -> dict:
        raise NotImplementedError


class StackConnector(Connector):
    """Honest availability probe for a platform (fail-open)."""

    def __init__(self, name: str, root: str):
        self.name = name
        self.root = Path(root)

    def status(self) -> dict:
        reachable = self.root.exists()
        return {"name": self.name, "reachable": reachable,
                "root": str(self.root),
                "detail": "reachable" if reachable else "not found (fail-open)"}

    def dispatch(self, task: str) -> dict:
        if not self.root.exists():
            return {"name": self.name, "ok": False,
                    "detail": "platform not reachable; cross-stack execution is v5"}
        return {"name": self.name, "ok": True,
                "detail": "reachable; cross-stack execution is v5"}


class Orchestrator:
    """Create agents, dispatch tasks, report stack status."""

    def __init__(self, ledger: Ledger | None = None,
                 agents_dir: Path | str = AGENTS_DIR):
        self.factory = AgentFactory(ledger=ledger, agents_dir=agents_dir)
        self.registry = AgentRegistry(agents_dir=agents_dir)
        self.connectors = [StackConnector(n, r) for n, r in STACK_ROOTS.items()]

    def create_agent(self, spec: AgentSpec) -> Agent:
        return self.factory.create(spec)

    def dispatch(self, agent_name: str, task: str) -> dict:
        agent = self.registry.load(agent_name)
        if agent is None:
            return {"ok": False, "detail": f"no such agent: {agent_name}"}
        return agent.run(task)

    def stack_status(self) -> list[dict]:
        return [c.status() for c in self.connectors]
