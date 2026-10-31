"""Task decomposition + concurrent delegation: DAG validation, true concurrency, failover,
partial-failure synthesis, and end-to-end execution over the actor mesh."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

import pytest

from extensions.mesh import (
    ActorContext,
    AgentMesh,
    ChaosConfig,
    ChaosTransport,
    MeshError,
    MeshNode,
    Orchestrator,
    PlanError,
    Status,
    Subtask,
    SupervisorPolicy,
    TaskPlan,
    WorkerActor,
)
from extensions.mesh.jsontypes import JSONObject


def run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(asyncio.wait_for(coro, 20))


class Node:
    def __init__(self, name: str, caps: set[str], *, fail: bool = False, delay: float = 0.0) -> None:
        self.name = name
        self.capabilities = frozenset(caps)
        self.fail = fail
        self.delay = delay
        self.calls: list[str] = []
        self.active = 0
        self.peak = 0

    async def run(self, subtask: Subtask, inputs: Mapping[str, JSONObject]) -> JSONObject:
        self.calls.append(subtask.id)
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(self.delay)
            if self.fail:
                raise RuntimeError(f"{self.name} down")
            return {"by": self.name, "inputs": sorted(inputs)}
        finally:
            self.active -= 1


def test_plan_validation() -> None:
    with pytest.raises(PlanError, match="cycle"):
        TaskPlan("p", (Subtask("a", "x", depends_on=("b",)), Subtask("b", "x", depends_on=("a",))))
    with pytest.raises(PlanError, match="unknown"):
        TaskPlan("p", (Subtask("a", "x", depends_on=("zz",)),))
    with pytest.raises(PlanError, match="duplicate"):
        TaskPlan("p", (Subtask("a", "x"), Subtask("a", "y")))
    plan = TaskPlan("p", (Subtask("c", "x", depends_on=("a", "b")), Subtask("a", "x"), Subtask("b", "x")))
    assert plan.topological_order()[-1] == "c"


def test_independent_subtasks_run_concurrently() -> None:
    node = Node("n", {"x"}, delay=0.05)

    async def go() -> None:
        orch = Orchestrator([node], max_concurrency=8)
        plan = TaskPlan("p", tuple(Subtask(f"s{i}", "x") for i in range(6)))
        t0 = asyncio.get_running_loop().time()
        res = await orch.execute(plan)
        assert res.complete
        assert asyncio.get_running_loop().time() - t0 < 0.2  # not 6 * 0.05 sequentially

    run(go())
    assert node.peak == 6


def test_concurrency_limit_is_respected() -> None:
    node = Node("n", {"x"}, delay=0.02)

    async def go() -> None:
        await Orchestrator([node], max_concurrency=2).execute(
            TaskPlan("p", tuple(Subtask(f"s{i}", "x") for i in range(6)))
        )

    run(go())
    assert node.peak == 2


def test_failover_to_next_capable_node() -> None:
    bad = Node("a-bad", {"x"}, fail=True)
    good = Node("b-good", {"x"})

    async def go() -> None:
        res = await Orchestrator([bad, good]).execute(TaskPlan("p", (Subtask("s", "x"),)))
        r = res.results["s"]
        assert r.status is Status.OK and r.node == "b-good" and r.attempts == 2

    run(go())


def test_required_failure_skips_dependents_but_optional_does_not() -> None:
    ok = Node("ok", {"good", "join"})
    bad = Node("bad", {"broken"}, fail=True)

    async def go() -> None:
        plan = TaskPlan(
            "p",
            (
                Subtask("req", "broken"),
                Subtask("opt", "broken", required=False),
                Subtask("good", "good"),
                Subtask("after_req", "join", depends_on=("req", "good")),
                Subtask("after_opt", "join", depends_on=("opt", "good")),
            ),
        )
        res = await Orchestrator([ok, bad]).execute(plan)
        assert not res.complete
        assert res.results["after_req"].status is Status.SKIPPED
        assert res.results["after_opt"].status is Status.OK
        assert res.results["after_opt"].output["inputs"] == ["good"]  # only existing inputs
        assert res.missing == ["after_req", "opt", "req"]
        assert set(res.synthesis["outputs"]) == {"good", "after_opt"}  # type: ignore[arg-type]

    run(go())


def test_unknown_capability_fails_cleanly() -> None:
    async def go() -> None:
        res = await Orchestrator([Node("n", {"x"})]).execute(TaskPlan("p", (Subtask("s", "nope"),)))
        assert res.results["s"].status is Status.FAILED and "no node" in str(res.results["s"].error)

    run(go())


def test_node_timeout_triggers_failover() -> None:
    slow = Node("a-slow", {"x"}, delay=5)
    fast = Node("b-fast", {"x"})

    async def go() -> None:
        res = await Orchestrator([slow, fast]).execute(TaskPlan("p", (Subtask("s", "x", timeout_s=0.05),)))
        assert res.results["s"].node == "b-fast"

    run(go())


class Splitter(WorkerActor):
    async def perform(self, capability: str, payload: JSONObject, inputs: JSONObject, ctx: ActorContext) -> JSONObject:
        text = str(payload.get("text", ""))
        return {"words": len(text.split())}


crash_once = {"done": False}


class Summer(WorkerActor):
    async def perform(self, capability: str, payload: JSONObject, inputs: JSONObject, ctx: ActorContext) -> JSONObject:
        if not crash_once["done"]:
            crash_once["done"] = True
            raise RuntimeError("crash mid-task")  # actor crash -> supervisor restart + redelivery
        total = 0
        for v in inputs.values():
            if isinstance(v, dict) and isinstance(v.get("words"), int):
                total += v["words"]  # type: ignore[operator]
        ctx.state.set("total", total)
        return {"total": total}


class Refuser(WorkerActor):
    async def perform(self, capability: str, payload: JSONObject, inputs: JSONObject, ctx: ActorContext) -> JSONObject:
        raise MeshError("not today")


def test_end_to_end_over_chaotic_mesh_with_actor_crash() -> None:
    async def go() -> None:
        chaos = ChaosTransport(ChaosConfig(duplicate=0.3, delay=0.3, seed=3))
        policy = SupervisorPolicy(backoff_base_s=0.001, watchdog_interval_s=0.01)
        async with AgentMesh(transport=chaos, policy=policy) as mesh:
            nodes = []
            for name, factory, caps in (
                ("split-a", Splitter, {"split"}),
                ("split-b", Splitter, {"split"}),
                ("refuser", Refuser, {"sum"}),
                ("summer", Summer, {"sum"}),
            ):
                mesh.spawn(name, factory)
                nodes.append(MeshNode(mesh, name, frozenset(caps)))
            plan = TaskPlan(
                "wc",
                (
                    Subtask("p1", "split", {"text": "a b c"}, timeout_s=2),
                    Subtask("p2", "split", {"text": "d e"}, timeout_s=2),
                    Subtask("total", "sum", depends_on=("p1", "p2"), timeout_s=2),
                ),
            )
            res = await Orchestrator(nodes).execute(plan)  # type: ignore[arg-type]
            assert res.complete, res.synthesis
            assert res.results["total"].output == {"total": 5}
            assert res.results["total"].node == "summer"  # refuser failed over
            await chaos.flush()
            await mesh.anti_entropy()
            assert mesh.converged() and mesh.state("split-a").get("total") == 5
            assert mesh.telemetry.snapshot()["actor.restarted"] == 1

    run(go())
