"""Actors: isolated state + a bounded mailbox + a single sequential handler.

An actor never shares mutable objects with another actor. It talks only through
``ActorContext`` (send / reply / ask, all schema-checked envelopes) and reads/writes shared
state only through its own CRDT ``StateReplica``. That is what removes global state and
data races by construction: within an actor, handlers run one at a time; across actors,
nothing is shared except immutable envelopes and commutative state deltas.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from .channel import BoundedChannel
from .clock import HybridLogicalClock
from .crdt import StateReplica
from .schema import Envelope
from .telemetry import Telemetry
from .jsontypes import JSONObject


class MeshAPI(Protocol):
    """The slice of ``AgentMesh`` an actor may use (keeps actors decoupled from the engine)."""

    telemetry: Telemetry

    async def send(
        self,
        sender: str,
        recipient: str,
        topic: str,
        payload: JSONObject,
        *,
        correlation_id: str | None = None,
        reply_to: str | None = None,
    ) -> Envelope: ...

    async def ask(
        self, sender: str, recipient: str, topic: str, payload: JSONObject, *, timeout: float
    ) -> Envelope: ...


class Actor(ABC):
    """Subclass and implement ``handle``. ``accepts`` lists the topics this actor serves;
    anything else is dead-lettered before ``handle`` runs."""

    accepts: frozenset[str] = frozenset()

    async def on_start(self, ctx: ActorContext) -> None:  # noqa: B027 — optional hook
        return None

    @abstractmethod
    async def handle(self, msg: Envelope, ctx: ActorContext) -> None: ...

    async def on_stop(self, ctx: ActorContext) -> None:  # noqa: B027 — optional hook
        return None


@dataclass(slots=True)
class ActorContext:
    name: str
    mesh: MeshAPI
    state: StateReplica
    clock: HybridLogicalClock

    @property
    def telemetry(self) -> Telemetry:
        return self.mesh.telemetry

    async def send(
        self, recipient: str, topic: str, payload: JSONObject, *, correlation_id: str | None = None
    ) -> Envelope:
        return await self.mesh.send(
            self.name, recipient, topic, payload, correlation_id=correlation_id
        )

    async def reply(self, to: Envelope, topic: str, payload: JSONObject) -> Envelope:
        if to.reply_to is None:
            raise ValueError(f"message {to.msg_id} did not request a reply")
        return await self.mesh.send(
            self.name, to.reply_to, topic, payload, correlation_id=to.correlation_id or to.msg_id
        )

    async def ask(
        self, recipient: str, topic: str, payload: JSONObject, *, timeout: float = 5.0
    ) -> Envelope:
        return await self.mesh.ask(self.name, recipient, topic, payload, timeout=timeout)


class CellStatus(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    RESTARTING = "restarting"
    FAILED = "failed"  # escalated: out of service
    STOPPED = "stopped"


ActorFactory = Callable[[], Actor]


@dataclass(eq=False)
class ActorCell:
    """Runtime envelope around one actor. Owned and mutated only by the supervisor."""

    name: str
    factory: ActorFactory
    mailbox: BoundedChannel[Envelope]
    ctx: ActorContext
    actor: Actor
    status: CellStatus = CellStatus.STARTING
    task: asyncio.Task[None] | None = None
    inflight: Envelope | None = None
    inflight_since: float | None = None
    processed: int = 0
    restarts: deque[float] = field(default_factory=deque)
    crash_counts: dict[str, int] = field(default_factory=dict)
    seen: OrderedDict[str, None] = field(default_factory=OrderedDict)
    seen_capacity: int = 4096
    last_error: str | None = None
    stalled: bool = False

    def mark_seen(self, msg_id: str) -> None:
        self.seen[msg_id] = None
        self.crash_counts.pop(msg_id, None)
        while len(self.seen) > self.seen_capacity:
            self.seen.popitem(last=False)

    def stall_age(self, now: float | None = None) -> float:
        if self.inflight_since is None:
            return 0.0
        return (time.monotonic() if now is None else now) - self.inflight_since
