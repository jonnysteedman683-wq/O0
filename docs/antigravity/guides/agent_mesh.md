# Agent Mesh — `extensions/mesh`

An asynchronous, self-healing, multi-agent execution engine for O0. Stdlib-only, `mypy --strict`
clean, and entirely inside Antigravity territory: it imports nothing from `o0.*` and writes
nothing under `state/`.

## Layering

```
types/errors                     jsontypes.py, errors.py
ordering + replicated state      clock.py (HLC) -> crdt.py (GCounter, PNCounter, LWWMap, StateReplica)
contracts                        schema.py (Schema, SchemaRegistry, upcasters, DriftReport, Envelope)
flow control + signals           channel.py, resilience.py, telemetry.py
transport adapters               transport.py (Loopback, Chaos; Transport protocol)
actors + self-healing + routing  actor.py -> supervisor.py -> mesh.py
tool federation                  tools.py (ToolRuntime, Transaction, subprocess_tool)
orchestration                    orchestrator.py (TaskPlan DAG, Orchestrator, MeshNode, WorkerActor)
```

No module imports a layer above it. Transport only sees JSON; actors only see `ActorContext`;
telemetry is a side channel that can never raise into the engine.

## Invariants

| # | Invariant | Enforced by |
|---|---|---|
| I1 | No shared mutable state between actors | actors communicate only via immutable `Envelope`s; shared state only via per-actor CRDT replicas |
| I2 | Replicas converge under any delivery order, duplication, loss | LWW merge is commutative/associative/idempotent; periodic anti-entropy repairs dropped gossip |
| I3 | Causal + total order of writes | Hybrid Logical Clock; remote clocks > `max_drift_ms` ahead are rejected, not adopted |
| I4 | Every payload is schema-valid before a handler sees it | sender-side validate (fail fast) + receiver-side coerce/upcast (drift → dead letter) |
| I5 | No unbounded queues | every mailbox is a `BoundedChannel` with an explicit `OverflowPolicy` |
| I6 | No lost in-flight work on crash | supervisor requeues the in-flight envelope at the mailbox front (attempt + 1) |
| I7 | No crash loops | poison messages dead-lettered after `poison_threshold`; restart intensity → escalation |
| I8 | Exactly-once *effects* under at-least-once delivery | receiver dedup by `msg_id` (marked only after successful handling) |
| I9 | Tool calls never spend beyond budget, even concurrently | `CostBudget` reserve → commit/refund |
| I10 | Non-idempotent tools are never blindly retried | retried only when the call provably never ran (breaker open / rate limited) |

## Quick start

```bash
python -m extensions.mesh                       # end-to-end self-healing demo
python -m pytest tests/extensions/test_mesh_*.py -q
python -m pip install mypy && python -m mypy --strict extensions/mesh
```

```python
from extensions.mesh import AgentMesh, MeshNode, Orchestrator, Subtask, TaskPlan, WorkerActor

class Researcher(WorkerActor):
    async def perform(self, capability, payload, inputs, ctx):
        ctx.state.set("last_query", payload["q"])     # replicated to every actor
        return {"answer": f"... {payload['q']}"}

async with AgentMesh() as mesh:
    mesh.spawn("r1", Researcher)
    mesh.spawn("r2", Researcher)
    orch = Orchestrator([MeshNode(mesh, n, frozenset({"research"})) for n in ("r1", "r2")])
    result = await orch.execute(TaskPlan("job", (
        Subtask("a", "research", {"q": "crdt"}),
        Subtask("b", "research", {"q": "hlc"}),
    )))
    result.complete, result.missing, result.synthesis
```

## Recovery paths

| Failure | Detection | Response |
|---|---|---|
| Handler exception | task exit | restart fresh instance (exp. backoff), requeue in-flight message |
| Same message keeps crashing | per-msg crash count | dead-letter after `poison_threshold` |
| Actor crash-looping | restarts in `window_s` | escalate: FAILED, mailbox closed, backlog dead-lettered; mesh continues |
| Deadlock / stall | watchdog: in-flight age > `stall_timeout_s` or `deadline_ms` passed | cancel + treat as crash |
| Malformed wire message | `Envelope.from_wire` | dead-letter (`transport`) |
| Schema drift | `SchemaRegistry.coerce` | upcast if migration exists, else dead-letter |
| Duplicate delivery | `msg_id` dedup | dropped, `message.duplicate` |
| Mailbox overload | channel policy | BLOCK → sender awaits (timeout); REJECT → `ChannelFullError`; DROP_OLDEST → dead-letter evicted |
| Tool transient error | `TransientToolError` / timeout / unknown exception | jittered backoff + parameter mutation |
| Upstream 429 | `RateLimitedError(retry_after)` | shared bucket frozen for all callers (no cascade) |
| Tool down | breaker opens after N failures | fast-fail, routed to next cheapest healthy tool; half-open probe recovers |
| Tool output drift | output schema | `ToolOutputDriftError` → fallback tool |
| Multi-step side effects fail midway | `Transaction` | compensations in reverse order |
| Node failure in a plan | exception / timeout | failover to next capable node; per-node breaker |
| Required subtask fails | plan scheduler | dependents SKIPPED; partial synthesis reports `missing` |

## Honest limits

- `subprocess_tool` is process/env/rlimit isolation, **not** a hostile-code security sandbox.
- Handler cancellation is cooperative; blocking sync code must go through `subprocess_tool`.
- Gossip is in-process today; `Transport` is the seam for a network adapter (see proposal).
- LWW resolves concurrent writes to the same key by timestamp — last writer wins, by design.
  Use distinct keys (or a counter CRDT) where both writes must survive.
