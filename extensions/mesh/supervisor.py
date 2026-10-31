"""Supervision tree root + watchdog: the self-healing layer.

What it guarantees:

  * **No lost in-flight work.** If a handler crashes or is killed by the watchdog, the
    message it was processing is requeued at the *front* of the mailbox (attempt + 1).
  * **Poison isolation.** A message that crashes its handler ``poison_threshold`` times is
    dead-lettered instead of crash-looping the actor forever.
  * **Bounded restarts.** Restarts back off exponentially; more than ``max_restarts`` within
    ``window_s`` escalates: the actor is marked FAILED, its mailbox is closed (senders fail
    fast) and its backlog dead-lettered. The rest of the mesh keeps running.
  * **Deadlock / stall detection.** A handler holding one message longer than
    ``stall_timeout_s`` (or past the message's own ``deadline_ms``) is cancelled and treated
    as a crash. Cancellation is cooperative: run blocking sync code through
    ``subprocess_tool`` so it can be killed.
  * **Feedback loops.** Each watchdog tick evaluates mailbox pressure, registered health
    probes (e.g. open circuit breakers, rate-limit storms) and runs the mesh's anti-entropy
    hook, emitting telemetry on state *transitions* only (no alert storms).
"""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .actor import ActorCell, CellStatus
from .channel import BoundedChannel, OverflowPolicy
from .errors import ChannelClosedError, SchemaError, UnknownSchemaError
from .schema import Envelope, SchemaRegistry
from .telemetry import EventKind, Telemetry
from .jsontypes import JSONObject

HealthProbe = Callable[[], list[str]]


@dataclass(frozen=True, slots=True)
class SupervisorPolicy:
    max_restarts: int = 5
    window_s: float = 30.0
    backoff_base_s: float = 0.01
    backoff_max_s: float = 1.0
    poison_threshold: int = 3
    stall_timeout_s: float = 10.0
    watchdog_interval_s: float = 0.05
    pressure_alarm: float = 0.8


@dataclass(frozen=True, slots=True)
class DeadLetter:
    actor: str
    reason: str
    envelope: Envelope | None = None
    raw: JSONObject | None = None
    wall_ms: int = 0


class Supervisor:
    def __init__(
        self,
        registry: SchemaRegistry,
        telemetry: Telemetry,
        policy: SupervisorPolicy = SupervisorPolicy(),
        *,
        dead_letter_capacity: int = 1000,
    ) -> None:
        self.registry = registry
        self.telemetry = telemetry
        self.policy = policy
        self.cells: dict[str, ActorCell] = {}
        self.dead_letters: BoundedChannel[DeadLetter] = BoundedChannel(
            dead_letter_capacity, policy=OverflowPolicy.DROP_OLDEST, name="dead-letters"
        )
        self.probes: list[HealthProbe] = []
        self.on_tick: list[Callable[[], Awaitable[None]]] = []
        self._watchdog: asyncio.Task[None] | None = None
        self._restart_tasks: set[asyncio.Task[None]] = set()
        self._stopping = False
        self._alarms: set[str] = set()

    # ---- dead letters --------------------------------------------------------------------

    def dead_letter(
        self,
        actor: str,
        reason: str,
        *,
        envelope: Envelope | None = None,
        raw: JSONObject | None = None,
    ) -> None:
        self.dead_letters.offer(
            DeadLetter(actor, reason, envelope, raw, time.time_ns() // 1_000_000)
        )
        self.telemetry.emit(
            EventKind.DEAD_LETTER,
            actor,
            reason=reason,
            msg_id=envelope.msg_id if envelope else None,
        )

    # ---- lifecycle -----------------------------------------------------------------------

    def start(self) -> None:
        if self._watchdog is None:
            self._watchdog = asyncio.get_running_loop().create_task(
                self._watch(), name="mesh-watchdog"
            )

    def adopt(self, cell: ActorCell) -> None:
        if cell.name in self.cells:
            raise ValueError(f"actor {cell.name!r} already exists")
        self.cells[cell.name] = cell
        self._launch(cell)

    def _launch(self, cell: ActorCell) -> None:
        cell.status = CellStatus.RUNNING
        cell.stalled = False
        task = asyncio.get_running_loop().create_task(self._run(cell), name=f"actor:{cell.name}")
        cell.task = task
        task.add_done_callback(functools.partial(self._on_exit, cell))
        self.telemetry.emit(EventKind.ACTOR_STARTED, cell.name, restarts=len(cell.restarts))

    async def _run(self, cell: ActorCell) -> None:
        await cell.actor.on_start(cell.ctx)
        while True:
            try:
                env = await cell.mailbox.recv()
            except ChannelClosedError:
                break
            if env.msg_id in cell.seen:
                self.telemetry.emit(EventKind.DUPLICATE_DROPPED, cell.name, msg_id=env.msg_id)
                continue
            if cell.actor.accepts and env.topic not in cell.actor.accepts:
                self.dead_letter(cell.name, f"topic {env.topic!r} not accepted", envelope=env)
                cell.mark_seen(env.msg_id)
                continue
            try:
                version, payload = self.registry.coerce(env.topic, env.schema_version, env.payload)
            except (SchemaError, UnknownSchemaError) as exc:
                self.telemetry.emit(
                    EventKind.SCHEMA_REJECTED, cell.name, where="mailbox", error=str(exc)
                )
                self.dead_letter(cell.name, f"schema: {exc}", envelope=env)
                cell.mark_seen(env.msg_id)
                continue
            msg = Envelope(
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
            cell.inflight, cell.inflight_since = env, time.monotonic()
            await cell.actor.handle(msg, cell.ctx)
            cell.mark_seen(env.msg_id)
            cell.inflight = cell.inflight_since = None
            cell.processed += 1
        await cell.actor.on_stop(cell.ctx)

    def _on_exit(self, cell: ActorCell, task: asyncio.Task[None]) -> None:
        if self._stopping or (cell.mailbox.closed and not task.cancelled() and task.exception() is None):
            cell.status = CellStatus.STOPPED
            self.telemetry.emit(EventKind.ACTOR_STOPPED, cell.name, processed=cell.processed)
            return
        if task.cancelled() and not cell.stalled:
            cell.status = CellStatus.STOPPED
            return
        exc = None if task.cancelled() else task.exception()
        reason = "stalled" if cell.stalled else f"{type(exc).__name__}: {exc}"
        cell.last_error = reason
        self.telemetry.emit(
            EventKind.ACTOR_CRASHED,
            cell.name,
            error=reason,
            msg_id=cell.inflight.msg_id if cell.inflight else None,
        )
        self._recover_inflight(cell, reason)
        now = time.monotonic()
        while cell.restarts and now - cell.restarts[0] > self.policy.window_s:
            cell.restarts.popleft()
        if len(cell.restarts) >= self.policy.max_restarts:
            self._escalate(cell, reason)
            return
        cell.restarts.append(now)
        cell.status = CellStatus.RESTARTING
        delay = min(
            self.policy.backoff_max_s,
            self.policy.backoff_base_s * (2 ** (len(cell.restarts) - 1)),
        )
        t = asyncio.get_running_loop().create_task(self._restart(cell, delay))
        self._restart_tasks.add(t)
        t.add_done_callback(self._restart_tasks.discard)

    def _recover_inflight(self, cell: ActorCell, reason: str) -> None:
        env = cell.inflight
        cell.inflight = cell.inflight_since = None
        if env is None:
            return
        n = cell.crash_counts.get(env.msg_id, 0) + 1
        cell.crash_counts[env.msg_id] = n
        if n >= self.policy.poison_threshold:
            cell.crash_counts.pop(env.msg_id, None)
            cell.mark_seen(env.msg_id)
            self.dead_letter(cell.name, f"poison after {n} crashes: {reason}", envelope=env)
            return
        try:
            cell.mailbox.push_front(env.with_attempt(env.attempt + 1))
        except ChannelClosedError:
            self.dead_letter(cell.name, "mailbox closed during recovery", envelope=env)

    async def _restart(self, cell: ActorCell, delay: float) -> None:
        await asyncio.sleep(delay)
        if self._stopping or cell.status is not CellStatus.RESTARTING:
            return
        cell.actor = cell.factory()  # fresh instance: no corrupted in-memory state survives
        self.telemetry.emit(EventKind.ACTOR_RESTARTED, cell.name, attempt=len(cell.restarts))
        self._launch(cell)

    def _escalate(self, cell: ActorCell, reason: str) -> None:
        cell.status = CellStatus.FAILED
        cell.mailbox.close()
        for env in cell.mailbox.drain():
            self.dead_letter(cell.name, "actor escalated (out of service)", envelope=env)
        self.telemetry.emit(
            EventKind.ACTOR_ESCALATED,
            cell.name,
            reason=reason,
            restarts=len(cell.restarts),
        )

    # ---- watchdog ------------------------------------------------------------------------

    async def _watch(self) -> None:
        p = self.policy
        while not self._stopping:
            await asyncio.sleep(p.watchdog_interval_s)
            now = time.monotonic()
            wall = time.time_ns() // 1_000_000
            for cell in list(self.cells.values()):
                if cell.status is not CellStatus.RUNNING:
                    continue
                env = cell.inflight
                overdue = env is not None and env.deadline_ms is not None and wall > env.deadline_ms
                if env is not None and (cell.stall_age(now) > p.stall_timeout_s or overdue):
                    cell.stalled = True
                    self.telemetry.emit(
                        EventKind.DEADLOCK_DETECTED,
                        cell.name,
                        msg_id=env.msg_id,
                        held_s=round(cell.stall_age(now), 4),
                        deadline_exceeded=overdue,
                    )
                    if cell.task is not None:
                        cell.task.cancel()
                key = f"pressure:{cell.name}"
                if cell.mailbox.pressure >= p.pressure_alarm:
                    if key not in self._alarms:
                        self._alarms.add(key)
                        self.telemetry.emit(
                            EventKind.BACKPRESSURE,
                            cell.name,
                            depth=len(cell.mailbox),
                            capacity=cell.mailbox.capacity,
                        )
                else:
                    self._alarms.discard(key)
            issues: set[str] = set()
            for probe in self.probes:
                try:
                    issues.update(f"probe:{i}" for i in probe())
                except Exception as exc:  # noqa: BLE001 — a broken probe is itself an issue
                    issues.add(f"probe:error:{type(exc).__name__}")
            for issue in issues - self._alarms:
                self.telemetry.emit(EventKind.DEGRADED, "watchdog", issue=issue)
            self._alarms = {a for a in self._alarms if not a.startswith("probe:")} | issues
            for hook in self.on_tick:
                try:
                    await hook()
                except Exception as exc:  # noqa: BLE001
                    self.telemetry.emit(EventKind.DEGRADED, "watchdog", issue=f"tick:{exc}")

    @property
    def alarms(self) -> frozenset[str]:
        return frozenset(self._alarms)

    async def stop(self, *, grace_s: float = 1.0) -> None:
        for cell in self.cells.values():
            cell.mailbox.close()
        running = [c.task for c in self.cells.values() if c.task and not c.task.done()]
        if running:
            _, pending = await asyncio.wait(running, timeout=grace_s)
            self._stopping = True
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        self._stopping = True
        for t in list(self._restart_tasks):
            t.cancel()
        await asyncio.gather(*self._restart_tasks, return_exceptions=True)
        if self._watchdog is not None:
            self._watchdog.cancel()
            await asyncio.gather(self._watchdog, return_exceptions=True)
            self._watchdog = None
