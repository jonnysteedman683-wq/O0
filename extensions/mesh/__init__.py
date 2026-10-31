"""O0 agent mesh: an asynchronous, self-healing, multi-agent execution engine.

Layering (no layer imports one above it)::

    types / errors                      shared vocabulary
    clock -> crdt                       ordering + conflict-free replicated state
    schema                              typed contracts, migration, drift, wire envelope
    channel / resilience / telemetry    backpressure, breakers, buckets, budgets, signals
    transport                           JSON-only adapters (loopback, chaos)
    actor -> supervisor -> mesh         isolated actors, self-healing, routing, gossip
    tools                               sandboxed, schema-checked, cost-aware tool federation
    orchestrator                        DAG decomposition + concurrent delegation

Stdlib-only and ``mypy --strict`` clean. Lives in Antigravity territory (``AGENTS.md``):
it imports nothing from ``o0.*`` and writes nothing under ``state/``.
"""

from __future__ import annotations

from .actor import Actor, ActorCell, ActorContext, CellStatus
from .channel import BoundedChannel, OverflowPolicy
from .clock import HLCTimestamp, HybridLogicalClock
from .crdt import GCounter, LWWMap, PNCounter, StateDelta, StateReplica
from .errors import (
    AskTimeoutError,
    BackpressureTimeoutError,
    BudgetExceededError,
    ChannelClosedError,
    ChannelFullError,
    CircuitOpenError,
    ClockDriftError,
    EscalationError,
    MalformedEnvelopeError,
    MeshError,
    NoRouteError,
    PermanentToolError,
    PlanError,
    RateLimitedError,
    RollbackError,
    SchemaError,
    ToolError,
    ToolOutputDriftError,
    ToolTimeoutError,
    TransientToolError,
)
from .mesh import AgentMesh
from .orchestrator import (
    AgentNode,
    MeshNode,
    Orchestrator,
    PlanResult,
    Status,
    Subtask,
    SubtaskResult,
    TaskPlan,
    WorkerActor,
    register_task_schemas,
)
from .resilience import BreakerState, CircuitBreaker, CostBudget, RetryPolicy, TokenBucket
from .schema import DriftReport, Envelope, Field, Kind, Schema, SchemaRegistry
from .supervisor import DeadLetter, Supervisor, SupervisorPolicy
from .telemetry import EventKind, InMemorySink, JsonlSink, Telemetry
from .tools import Isolation, ToolOutcome, ToolRuntime, ToolSpec, Transaction, subprocess_tool
from .transport import ChaosConfig, ChaosTransport, LoopbackTransport, Transport

__all__ = [
    "Actor", "ActorCell", "ActorContext", "AgentMesh", "AgentNode", "AskTimeoutError",
    "BackpressureTimeoutError", "BoundedChannel", "BreakerState", "BudgetExceededError",
    "CellStatus", "ChannelClosedError", "ChannelFullError", "ChaosConfig", "ChaosTransport",
    "CircuitBreaker", "CircuitOpenError", "ClockDriftError", "CostBudget", "DeadLetter",
    "DriftReport", "Envelope", "EscalationError", "EventKind", "Field", "GCounter",
    "HLCTimestamp", "HybridLogicalClock", "InMemorySink", "Isolation", "JsonlSink", "Kind",
    "LWWMap", "LoopbackTransport", "MalformedEnvelopeError", "MeshError", "MeshNode",
    "NoRouteError", "Orchestrator", "OverflowPolicy", "PNCounter", "PermanentToolError",
    "PlanError", "PlanResult", "RateLimitedError", "RetryPolicy", "RollbackError", "Schema",
    "SchemaError", "SchemaRegistry", "StateDelta", "StateReplica", "Status", "Subtask",
    "SubtaskResult", "Supervisor", "SupervisorPolicy", "TaskPlan", "Telemetry", "TokenBucket",
    "ToolError", "ToolOutcome", "ToolOutputDriftError", "ToolRuntime", "ToolSpec",
    "ToolTimeoutError", "Transaction", "TransientToolError", "Transport", "WorkerActor",
    "register_task_schemas", "subprocess_tool",
]
