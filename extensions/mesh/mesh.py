"""``AgentMesh`` — the composition root.

Wires clock, schema registry, transport, supervisor and per-actor CRDT replicas together.
Concerns stay separated: the mesh routes envelopes and replicates state; the supervisor
owns actor lifecycles; the transport only moves JSON; tools and orchestration live in their
own modules and talk to the mesh through envelopes.

Message path (every hop typed and checked)::

    ctx.send -> schema validate (sender, fail fast) -> HLC stamp -> Envelope.to_wire
      -> Transport -> Envelope.from_wire (malformed -> dead letter)
      -> HLC merge (drift -> dead letter) -> recipient mailbox (bounded; backpressure)
      -> dedup by msg_id -> schema coerce/upcast (drift -> dead letter) -> Actor.handle

State path: ``ctx.state.set(k, v)`` emits a ``StateDelta`` that is gossiped as a
``mesh.state.delta`` envelope over the same (possibly lossy) transport; the watchdog runs
periodic full-state anti-entropy, so replicas converge even when gossip is dropped.
"""

from __future__ import annotations

import asyncio
import functools
import re
import time
import uuid
from collections import OrderedDict
from types import TracebackType

from .actor import ActorCell, ActorContext, ActorFactory, CellStatus
from .channel import BoundedChannel, OverflowPolicy
from .clock import HybridLogicalClock
from .crdt import LWWMap, StateDelta, StateReplica
from .errors import (
    ActorNotFoundError,
    AskTimeoutError,
    ClockDriftError,
    EscalationError,
    MalformedEnvelopeError,
    MeshError,
    SchemaError,
    UnknownSchemaError,
)
from .schema import Envelope, Field, Kind, Schema, SchemaRegistry
from .supervisor import Supervisor, SupervisorPolicy
from .telemetry import EventKind, Telemetry
from .transport import LoopbackTransport, Transport
from .jsontypes import JSONObject

REPLY_ADDR = "mesh.reply"  # actor names cannot contain '.', so these never collide
STATE_ADDR = "mesh.state"
STATE_TOPIC = "mesh.state.delta"
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

STATE_DELTA_SCHEMA = Schema(
    STATE_TOPIC,
    1,
    (
        Field("key", Kind.STR, max_len=512),
        Field("value", Kind.JSON, nullable=True),
        Field("deleted", Kind.BOOL),
        Field("ts", Kind.STR, max_len=200),
    ),
)


class AgentMesh:
    def __init__(
        self,
        *,
        node_id: str = "o0",
        registry: SchemaRegistry | None = None,
        transport: Transport | None = None,
        telemetry: Telemetry | None = None,
        policy: SupervisorPolicy = SupervisorPolicy(),
        send_timeout_s: float = 1.0,
        anti_entropy_every: int = 10,
    ) -> None:
        if not _NAME.match(node_id):
            raise ValueError(f"invalid node_id {node_id!r}")
        self.node_id = node_id
        self.registry = registry or SchemaRegistry()
        if STATE_TOPIC not in self.registry:
            self.registry.register(STATE_DELTA_SCHEMA)
        self.telemetry = telemetry or Telemetry()
        self.transport: Transport = transport or LoopbackTransport()
        self.clock = HybridLogicalClock(node_id)
        self.supervisor = Supervisor(self.registry, self.telemetry, policy)
        self.send_timeout_s = send_timeout_s
        self._pending: dict[str, asyncio.Future[Envelope]] = {}
        self._resolved: OrderedDict[str, None] = OrderedDict()
        self._replicas: dict[str, StateReplica] = {}
        self._gossip: set[asyncio.Task[None]] = set()
        self._ticks = 0
        self._anti_entropy_every = max(1, anti_entropy_every)
        self._started = False
        self.transport.bind(self._inbound)
        self.supervisor.on_tick.append(self._tick)

    # ---- lifecycle -----------------------------------------------------------------------

    async def __aenter__(self) -> AgentMesh:
        self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.stop()

    def start(self) -> None:
        self.supervisor.start()
        self._started = True

    async def stop(self, *, grace_s: float = 1.0) -> None:
        await self.supervisor.stop(grace_s=grace_s)
        for t in list(self._gossip):
            t.cancel()
        await asyncio.gather(*self._gossip, return_exceptions=True)
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(MeshError("mesh stopped"))
        self._pending.clear()
        await self.transport.close()
        self._started = False

    # ---- actors --------------------------------------------------------------------------

    def spawn(
        self,
        name: str,
        factory: ActorFactory,
        *,
        capacity: int = 256,
        overflow: OverflowPolicy = OverflowPolicy.BLOCK,
    ) -> ActorCell:
        if not self._started:
            raise MeshError("start the mesh before spawning actors")
        if not _NAME.match(name):
            raise ValueError(f"invalid actor name {name!r} (allowed: [A-Za-z0-9_-]{{1,64}})")
        clock = HybridLogicalClock(f"{self.node_id}-{name}")
        replica = StateReplica(clock)
        for other in self._replicas.values():  # late joiner starts from current state
            replica.merge_from(other.state)
        replica.subscribe(functools.partial(self._on_local_delta, name))
        self._replicas[name] = replica

        def on_drop(env: Envelope) -> None:
            self.supervisor.dead_letter(name, "mailbox overflow (drop_oldest)", envelope=env)

        mailbox: BoundedChannel[Envelope] = BoundedChannel(
            capacity, policy=overflow, name=f"mailbox:{name}", on_drop=on_drop
        )
        ctx = ActorContext(name, self, replica, clock)
        cell = ActorCell(name=name, factory=factory, mailbox=mailbox, ctx=ctx, actor=factory())
        self.supervisor.adopt(cell)
        return cell

    def cell(self, name: str) -> ActorCell:
        try:
            return self.supervisor.cells[name]
        except KeyError as exc:
            raise ActorNotFoundError(name) from exc

    def state(self, name: str) -> StateReplica:
        return self._replicas[name]

    # ---- messaging -----------------------------------------------------------------------

    async def send(
        self,
        sender: str,
        recipient: str,
        topic: str,
        payload: JSONObject,
        *,
        correlation_id: str | None = None,
        reply_to: str | None = None,
        deadline_ms: int | None = None,
    ) -> Envelope:
        schema = self.registry.get(topic)  # UnknownSchemaError -> caller bug, fail fast
        validated = schema.validate(payload)  # SchemaError -> caller bug, fail fast
        replica = self._replicas.get(sender)
        clock = replica.clock if replica is not None else self.clock
        env = Envelope(
            topic=topic,
            schema_version=schema.version,
            sender=sender,
            recipient=recipient,
            ts=clock.now(),
            payload=validated,
            correlation_id=correlation_id,
            reply_to=reply_to,
            deadline_ms=deadline_ms,
        )
        await self.transport.send(env.to_wire())
        return env

    async def ask(
        self,
        sender: str,
        recipient: str,
        topic: str,
        payload: JSONObject,
        *,
        timeout: float = 5.0,
        deadline_s: float | None = None,
    ) -> Envelope:
        """Request/reply. ``deadline_s`` (default: ``timeout``) is stamped on the request so
        the watchdog can kill a handler that is still working on an abandoned request."""
        cid = uuid.uuid4().hex
        fut: asyncio.Future[Envelope] = asyncio.get_running_loop().create_future()
        self._pending[cid] = fut
        deadline = time.time_ns() // 1_000_000 + int(1000 * (deadline_s or timeout))
        try:
            await self.send(
                sender,
                recipient,
                topic,
                payload,
                correlation_id=cid,
                reply_to=REPLY_ADDR,
                deadline_ms=deadline,
            )
            try:
                return await asyncio.wait_for(fut, timeout)
            except TimeoutError as exc:
                raise AskTimeoutError(f"{recipient}:{topic} no reply in {timeout}s") from exc
        finally:
            self._pending.pop(cid, None)

    async def _inbound(self, raw: object) -> None:
        try:
            env = Envelope.from_wire(raw)
        except MalformedEnvelopeError as exc:
            self.supervisor.dead_letter(
                "transport", f"malformed: {exc}", raw=raw if isinstance(raw, dict) else None
            )
            return
        try:
            self.clock.update(env.ts)
        except ClockDriftError as exc:
            self.supervisor.dead_letter("transport", f"clock drift: {exc}", envelope=env)
            return

        if env.recipient == REPLY_ADDR:
            self._resolve_reply(env)
            return
        if env.recipient == STATE_ADDR:
            self._apply_remote_delta(env)
            return

        cell = self.supervisor.cells.get(env.recipient)
        if cell is None:
            self.supervisor.dead_letter(env.recipient, "no such actor", envelope=env)
            raise ActorNotFoundError(env.recipient)
        if cell.status in (CellStatus.FAILED, CellStatus.STOPPED):
            self.supervisor.dead_letter(env.recipient, f"actor {cell.status.value}", envelope=env)
            raise EscalationError(f"{env.recipient} is {cell.status.value}")
        # BLOCK mailboxes push backpressure to the sender; REJECT raises ChannelFullError.
        await cell.mailbox.send(env, timeout=self.send_timeout_s)

    def _resolve_reply(self, env: Envelope) -> None:
        cid = env.correlation_id or ""
        fut = self._pending.get(cid)
        if cid in self._resolved:  # duplicate delivery of an already-consumed reply
            self.telemetry.emit(EventKind.DUPLICATE_DROPPED, REPLY_ADDR, msg_id=env.msg_id)
            return
        if fut is None or fut.done():
            self.supervisor.dead_letter(REPLY_ADDR, "orphan or late reply", envelope=env)
            return
        self._resolved[cid] = None
        while len(self._resolved) > 4096:
            self._resolved.popitem(last=False)
        try:
            version, payload = self.registry.coerce(env.topic, env.schema_version, env.payload)
        except (SchemaError, UnknownSchemaError) as exc:
            fut.set_exception(exc)
            return
        fut.set_result(
            Envelope(
                env.topic,
                version,
                env.sender,
                env.recipient,
                env.ts,
                payload,
                env.msg_id,
                env.correlation_id,
                env.reply_to,
                env.attempt,
                env.deadline_ms,
            )
        )

    # ---- replicated state ----------------------------------------------------------------

    def _on_local_delta(self, origin: str, delta: StateDelta) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no loop: anti-entropy will carry it
        t = loop.create_task(self._publish_delta(origin, delta))
        self._gossip.add(t)
        t.add_done_callback(self._gossip.discard)

    async def _publish_delta(self, origin: str, delta: StateDelta) -> None:
        try:
            await self.send(origin, STATE_ADDR, STATE_TOPIC, delta.to_wire())
        except MeshError:
            pass  # lossy by design; anti-entropy repairs it

    def _apply_remote_delta(self, env: Envelope) -> None:
        try:
            STATE_DELTA_SCHEMA.validate(env.payload)
            delta = StateDelta.from_wire(env.payload)
        except (SchemaError, MalformedEnvelopeError) as exc:
            self.supervisor.dead_letter(STATE_ADDR, f"bad delta: {exc}", envelope=env)
            return
        changed = 0
        for name, replica in self._replicas.items():
            if name != env.sender:
                try:
                    changed += replica.apply(delta)
                except ClockDriftError as exc:
                    self.supervisor.dead_letter(name, f"delta drift: {exc}", envelope=env)
        if changed:
            self.telemetry.emit(EventKind.STATE_SYNC, env.sender, key=delta.key, replicas=changed)

    async def anti_entropy(self) -> int:
        """Full-state merge across all replicas. Returns entries repaired."""
        merged = LWWMap()
        for r in self._replicas.values():
            merged = merged.merge(r.state)
        repaired = sum(r.merge_from(merged) for r in self._replicas.values())
        if repaired:
            self.telemetry.emit(EventKind.STATE_SYNC, "anti-entropy", repaired=repaired)
        return repaired

    async def _tick(self) -> None:
        self._ticks += 1
        if self._ticks % self._anti_entropy_every == 0:
            await self.anti_entropy()

    def converged(self) -> bool:
        snaps = [r.state for r in self._replicas.values()]
        return all(s == snaps[0] for s in snaps[1:])

    # ---- introspection -------------------------------------------------------------------

    async def quiesce(self, *, timeout: float = 5.0, settle_s: float = 0.01) -> None:
        """Wait until no mailbox has work and no gossip is in flight (tests, shutdown)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            busy = any(
                len(c.mailbox) or c.inflight is not None or c.status is CellStatus.RESTARTING
                for c in self.supervisor.cells.values()
                if c.status is not CellStatus.FAILED
            )
            if not busy and not self._gossip:
                await asyncio.sleep(settle_s)
                if not self._gossip:
                    return
            await asyncio.sleep(settle_s)
        raise TimeoutError("mesh did not quiesce")

    def health(self) -> dict[str, str]:
        return {n: c.status.value for n, c in sorted(self.supervisor.cells.items())}
