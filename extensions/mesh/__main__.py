"""``python -m extensions.mesh`` — end-to-end self-healing demo (no network, no core writes).

Spins up a mesh over a lossy ``ChaosTransport``, three specialist workers (one of which
crashes on its first message), a tool runtime with a rate-limited, flaky primary tool and a
cheaper-but-weaker fallback, and runs a 4-step plan. Prints the synthesis and the telemetry
counters that show each recovery path firing.
"""

from __future__ import annotations

import asyncio
import json

from .actor import ActorContext
from .errors import RateLimitedError, TransientToolError
from .jsontypes import JSONObject
from .mesh import AgentMesh
from .orchestrator import MeshNode, Orchestrator, Subtask, TaskPlan, WorkerActor
from .resilience import CostBudget, RetryPolicy
from .schema import Field, Kind, Schema
from .supervisor import SupervisorPolicy
from .telemetry import Telemetry
from .tools import ToolRuntime, ToolSpec
from .transport import ChaosConfig, ChaosTransport

Q_IN = Schema("demo.query", 1, (Field("q", Kind.STR), Field("k", Kind.INT)))
Q_OUT = Schema("demo.hits", 1, (Field("hits", Kind.STR_LIST),))


def build_tools(tel: Telemetry) -> ToolRuntime:
    rt = ToolRuntime(
        telemetry=tel, retry=RetryPolicy(max_attempts=4, base_delay_s=0.01), breaker_threshold=6
    )
    calls = {"n": 0}

    async def premium(p: JSONObject) -> JSONObject:
        calls["n"] += 1
        k = p["k"]
        assert isinstance(k, int)
        if calls["n"] == 1:
            raise RateLimitedError(retry_after_s=0.02)
        if k > 3:
            raise TransientToolError("payload too large")
        return {"hits": [f"premium:{p['q']}:{i}" for i in range(k)]}

    async def basic(p: JSONObject) -> JSONObject:
        return {"hits": [f"basic:{p['q']}"]}

    def shrink(params: JSONObject, _err: Exception, _attempt: int) -> JSONObject | None:
        k = params.get("k")
        return {**params, "k": max(1, k // 2)} if isinstance(k, int) and k > 1 else None

    rt.register(
        ToolSpec("search.premium", Q_IN, Q_OUT, frozenset({"search"}), cost_per_call=0.5,
                 rate_per_s=50, burst=2),
        premium,
        mutators=[shrink],
    )
    rt.register(ToolSpec("search.basic", Q_IN, Q_OUT, frozenset({"search"}), cost_per_call=1.0), basic)
    return rt


class Researcher(WorkerActor):
    def __init__(self, tools: ToolRuntime, budget: CostBudget) -> None:
        self.tools, self.budget = tools, budget

    async def perform(self, capability: str, payload: JSONObject, inputs: JSONObject, ctx: ActorContext) -> JSONObject:
        out = await self.tools.route("search", {"q": payload.get("q", ""), "k": 8}, budget=self.budget)
        ctx.state.set(f"research:{payload.get('q')}", out.tool)
        hits = out.output.get("hits")
        return {"hits": hits if isinstance(hits, list) else [], "tool": out.tool, "attempts": out.attempts}


crashed = {"once": False}


class Writer(WorkerActor):
    async def perform(self, capability: str, payload: JSONObject, inputs: JSONObject, ctx: ActorContext) -> JSONObject:
        if not crashed["once"]:
            crashed["once"] = True
            raise RuntimeError("simulated writer crash")  # supervisor restarts + redelivers
        n = 0
        for v in inputs.values():
            hits = v.get("hits") if isinstance(v, dict) else None
            n += len(hits) if isinstance(hits, list) else 0
        ctx.state.set("report", f"{n} findings")
        return {"report": f"synthesised {n} findings from {sorted(inputs)}"}


async def main() -> None:
    tel = Telemetry()
    chaos = ChaosTransport(ChaosConfig(duplicate=0.3, delay=0.3, seed=11, spare_topics=frozenset()))
    tools = build_tools(tel)
    budget = CostBudget(10.0)
    async with AgentMesh(transport=chaos, telemetry=tel,
                         policy=SupervisorPolicy(stall_timeout_s=2.0)) as mesh:
        mesh.spawn("researcher-a", lambda: Researcher(tools, budget))
        mesh.spawn("researcher-b", lambda: Researcher(tools, budget))
        mesh.spawn("writer", Writer)
        orch = Orchestrator(
            [
                MeshNode(mesh, "researcher-a", frozenset({"research"})),
                MeshNode(mesh, "researcher-b", frozenset({"research"})),
                MeshNode(mesh, "writer", frozenset({"write"})),
            ],
            telemetry=tel,
        )
        plan = TaskPlan("demo", (
            Subtask("r1", "research", {"q": "crdt"}, timeout_s=3),
            Subtask("r2", "research", {"q": "hlc"}, timeout_s=3),
            Subtask("r3", "research", {"q": "actors"}, timeout_s=3),
            Subtask("w", "write", depends_on=("r1", "r2", "r3"), timeout_s=3),
        ))
        result = await orch.execute(plan)
        await chaos.flush()
        await mesh.anti_entropy()
        print(json.dumps(result.synthesis, indent=2, sort_keys=True))
        print("complete:", result.complete, "| converged:", mesh.converged(), "| budget left:",
              round(budget.remaining, 2))
        print("telemetry:", json.dumps(dict(sorted(tel.snapshot().items())), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
