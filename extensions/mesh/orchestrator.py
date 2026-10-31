"""Dynamic task decomposition and concurrent delegation across specialised agent nodes.

``Orchestrator.execute(plan)`` runs a DAG of ``Subtask``s:

  * Subtasks start the moment their dependencies finish (no artificial waves), bounded by
    ``max_concurrency``.
  * Each subtask is routed to a node advertising its capability — least-loaded, healthy
    first. A node failure fails over to the next capable node; per-node circuit breakers
    stop a sick node from absorbing every retry.
  * A failed *required* subtask skips its dependents; an *optional* failure does not block
    dependents (they receive only the inputs that exist). The plan still returns: partial
    outputs are synthesised and the result says exactly what is missing.

Nodes can be plain Python (``AgentNode`` protocol) or remote actors via ``MeshNode``, which
speaks ``task.run`` / ``task.result`` envelopes over the mesh — so the same plan runs
in-process or across the actor mesh unchanged.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from .actor import Actor, ActorContext
from .errors import MeshError, PlanError
from .mesh import AgentMesh
from .resilience import CircuitBreaker
from .schema import Envelope, Field, Kind, Schema, SchemaRegistry
from .telemetry import EventKind, Telemetry
from .jsontypes import JSONObject, JSONValue


@dataclass(frozen=True, slots=True)
class Subtask:
    id: str
    capability: str
    payload: JSONObject = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    required: bool = True
    timeout_s: float = 30.0


@dataclass(frozen=True, slots=True)
class TaskPlan:
    task_id: str
    subtasks: tuple[Subtask, ...]

    def __post_init__(self) -> None:
        ids = [s.id for s in self.subtasks]
        if len(ids) != len(set(ids)):
            raise PlanError(f"{self.task_id}: duplicate subtask ids")
        known = set(ids)
        for s in self.subtasks:
            missing = [d for d in s.depends_on if d not in known]
            if missing:
                raise PlanError(f"{s.id} depends on unknown {missing}")
        self.topological_order()  # raises on cycles

    def topological_order(self) -> list[str]:
        indeg = {s.id: len(s.depends_on) for s in self.subtasks}
        children: dict[str, list[str]] = {s.id: [] for s in self.subtasks}
        for s in self.subtasks:
            for d in s.depends_on:
                children[d].append(s.id)
        ready = sorted(i for i, n in indeg.items() if n == 0)
        order: list[str] = []
        while ready:
            n = ready.pop(0)
            order.append(n)
            for c in sorted(children[n]):
                indeg[c] -= 1
                if indeg[c] == 0:
                    ready.append(c)
        if len(order) != len(self.subtasks):
            raise PlanError(f"{self.task_id}: dependency cycle")
        return order


class Status(StrEnum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class SubtaskResult:
    subtask_id: str
    status: Status
    output: JSONObject = field(default_factory=dict)
    node: str | None = None
    attempts: int = 0
    error: str | None = None
    duration_s: float = 0.0


@dataclass(frozen=True, slots=True)
class PlanResult:
    task_id: str
    complete: bool
    results: Mapping[str, SubtaskResult]
    synthesis: JSONObject

    @property
    def missing(self) -> list[str]:
        return sorted(k for k, r in self.results.items() if r.status is not Status.OK)


class AgentNode(Protocol):
    name: str
    capabilities: frozenset[str]

    async def run(self, subtask: Subtask, inputs: Mapping[str, JSONObject]) -> JSONObject: ...


class Synthesizer(Protocol):
    def __call__(self, plan: TaskPlan, results: Mapping[str, SubtaskResult]) -> JSONObject: ...


def merge_synthesizer(plan: TaskPlan, results: Mapping[str, SubtaskResult]) -> JSONObject:
    """Default: keyed outputs of successful subtasks plus an explicit gap report."""
    outputs: dict[str, JSONValue] = {
        k: dict(r.output) for k, r in results.items() if r.status is Status.OK
    }
    return {
        "task_id": plan.task_id,
        "outputs": outputs,
        "missing": list[JSONValue](
            sorted(k for k, r in results.items() if r.status is not Status.OK)
        ),
        "errors": {k: r.error for k, r in results.items() if r.error},
    }


class Orchestrator:
    def __init__(
        self,
        nodes: Sequence[AgentNode],
        *,
        telemetry: Telemetry | None = None,
        max_concurrency: int = 8,
        node_failure_threshold: int = 3,
        node_recovery_s: float = 5.0,
        synthesizer: Synthesizer = merge_synthesizer,
    ) -> None:
        names = [n.name for n in nodes]
        if len(names) != len(set(names)):
            raise ValueError("node names must be unique")
        self.nodes = list(nodes)
        self.telemetry = telemetry or Telemetry()
        self._sem = asyncio.Semaphore(max(1, max_concurrency))
        self._load: dict[str, int] = {n.name: 0 for n in nodes}
        self._breakers = {
            n.name: CircuitBreaker(
                n.name, failure_threshold=node_failure_threshold, recovery_s=node_recovery_s
            )
            for n in nodes
        }
        self.synthesizer = synthesizer

    def _candidates(self, capability: str) -> list[AgentNode]:
        capable = [n for n in self.nodes if capability in n.capabilities]
        return sorted(
            capable,
            key=lambda n: (self._breakers[n.name].state.value == "open", self._load[n.name], n.name),
        )

    async def execute(self, plan: TaskPlan) -> PlanResult:
        by_id = {s.id: s for s in plan.subtasks}
        results: dict[str, SubtaskResult] = {}
        running: dict[str, asyncio.Task[SubtaskResult]] = {}
        pending = set(by_id)

        def resolvable(s: Subtask) -> bool:
            return all(d in results for d in s.depends_on)

        while pending or running:
            for sid in sorted(pending):
                s = by_id[sid]
                if not resolvable(s):
                    continue
                pending.discard(sid)
                blocked = [
                    d
                    for d in s.depends_on
                    if results[d].status is not Status.OK and by_id[d].required
                ]
                if blocked:
                    results[sid] = SubtaskResult(
                        sid, Status.SKIPPED, error=f"required dependency failed: {blocked}"
                    )
                    self.telemetry.emit(EventKind.SUBTASK_DONE, sid, status="skipped")
                    continue
                inputs = {
                    d: dict(results[d].output)
                    for d in s.depends_on
                    if results[d].status is Status.OK
                }
                running[sid] = asyncio.get_running_loop().create_task(self._run_one(s, inputs))
            if not running:
                if pending:  # unreachable for a validated DAG; defensive
                    raise PlanError(f"stuck subtasks {sorted(pending)}")
                break
            done, _ = await asyncio.wait(running.values(), return_when=asyncio.FIRST_COMPLETED)
            for sid, t in list(running.items()):
                if t in done:
                    results[sid] = t.result()
                    del running[sid]

        complete = all(r.status is Status.OK for r in results.values())
        synthesis = self.synthesizer(plan, results)
        self.telemetry.emit(
            EventKind.PLAN_DONE,
            plan.task_id,
            complete=complete,
            missing=list[JSONValue](
                sorted(k for k, r in results.items() if r.status is not Status.OK)
            ),
        )
        return PlanResult(plan.task_id, complete, dict(results), synthesis)

    async def _run_one(self, s: Subtask, inputs: Mapping[str, JSONObject]) -> SubtaskResult:
        t0 = time.monotonic()
        errors: list[str] = []
        attempts = 0
        async with self._sem:
            for node in self._candidates(s.capability):
                br = self._breakers[node.name]
                try:
                    br.acquire()
                except MeshError as exc:
                    errors.append(f"{node.name}: {exc}")
                    continue
                attempts += 1
                self._load[node.name] += 1
                try:
                    out = await asyncio.wait_for(node.run(s, inputs), s.timeout_s)
                    br.record_success()
                    res = SubtaskResult(
                        s.id, Status.OK, out, node.name, attempts, None, time.monotonic() - t0
                    )
                    self.telemetry.emit(EventKind.SUBTASK_DONE, s.id, status="ok", node=node.name)
                    return res
                except asyncio.CancelledError:
                    br.release_probe()
                    raise
                except Exception as exc:  # noqa: BLE001 — node failure => failover
                    br.record_failure()
                    errors.append(f"{node.name}: {type(exc).__name__}: {exc}")
                finally:
                    self._load[node.name] -= 1
        error = "; ".join(errors) if errors else f"no node offers capability {s.capability!r}"
        self.telemetry.emit(EventKind.SUBTASK_DONE, s.id, status="failed", error=error)
        return SubtaskResult(
            s.id, Status.FAILED, {}, None, attempts, error, time.monotonic() - t0
        )


# ---- mesh bridge -------------------------------------------------------------------------

TASK_RUN = Schema(
    "task.run",
    1,
    (
        Field("subtask_id", Kind.STR, max_len=128),
        Field("capability", Kind.STR, max_len=128),
        Field("payload", Kind.OBJECT),
        Field("inputs", Kind.OBJECT),
    ),
)
TASK_RESULT = Schema(
    "task.result",
    1,
    (
        Field("subtask_id", Kind.STR, max_len=128),
        Field("ok", Kind.BOOL),
        Field("output", Kind.OBJECT),
        Field("error", Kind.STR, required=False, nullable=True, max_len=2000),
    ),
)


def register_task_schemas(registry: SchemaRegistry) -> None:
    for s in (TASK_RUN, TASK_RESULT):
        if s.name not in registry:
            registry.register(s)


class WorkerActor(Actor):
    """Base for mesh-resident specialists. Implement ``perform``; errors become
    ``ok=false`` results (the orchestrator then fails over) rather than actor crashes."""

    accepts = frozenset({TASK_RUN.name})

    async def perform(
        self, capability: str, payload: JSONObject, inputs: JSONObject, ctx: ActorContext
    ) -> JSONObject:
        raise NotImplementedError

    async def handle(self, msg: Envelope, ctx: ActorContext) -> None:
        p = msg.payload
        sid, cap = str(p["subtask_id"]), str(p["capability"])
        payload = p["payload"] if isinstance(p["payload"], dict) else {}
        inputs = p["inputs"] if isinstance(p["inputs"], dict) else {}
        try:
            out = await self.perform(cap, payload, inputs, ctx)
            result: JSONObject = {"subtask_id": sid, "ok": True, "output": out}
        except MeshError as exc:
            result = {"subtask_id": sid, "ok": False, "output": {}, "error": str(exc)}
        await ctx.reply(msg, TASK_RESULT.name, result)


class MeshNode:
    """``AgentNode`` adapter that delegates a subtask to an actor over the mesh."""

    def __init__(
        self, mesh: AgentMesh, actor: str, capabilities: frozenset[str], *, sender: str = "orchestrator"
    ) -> None:
        register_task_schemas(mesh.registry)
        self.mesh = mesh
        self.name = actor
        self.capabilities = capabilities
        self.sender = sender

    async def run(self, subtask: Subtask, inputs: Mapping[str, JSONObject]) -> JSONObject:
        reply = await self.mesh.ask(
            self.sender,
            self.name,
            TASK_RUN.name,
            {
                "subtask_id": subtask.id,
                "capability": subtask.capability,
                "payload": dict(subtask.payload),
                "inputs": {k: dict(v) for k, v in inputs.items()},
            },
            timeout=subtask.timeout_s,
        )
        if reply.topic != TASK_RESULT.name:
            raise MeshError(f"unexpected reply topic {reply.topic}")
        if not reply.payload.get("ok"):
            raise MeshError(str(reply.payload.get("error") or "worker reported failure"))
        out = reply.payload.get("output")
        return out if isinstance(out, dict) else {}
