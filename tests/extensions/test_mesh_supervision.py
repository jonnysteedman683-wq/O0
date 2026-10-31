"""Actor mesh self-healing: crash recovery, poison isolation, escalation, deadlock detection,
dedup under duplicate delivery, malformed payloads, backpressure, and state convergence."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from extensions.mesh import (
    Actor,
    ActorContext,
    AgentMesh,
    AskTimeoutError,
    CellStatus,
    ChannelFullError,
    ChaosConfig,
    ChaosTransport,
    Envelope,
    EscalationError,
    EventKind,
    Field,
    Kind,
    OverflowPolicy,
    Schema,
    SchemaError,
    SchemaRegistry,
    SupervisorPolicy,
    Telemetry,
)

WORK = Schema("work", 1, (Field("n", Kind.INT),))
ECHO = Schema("echo", 1, (Field("n", Kind.INT),))
FAST = SupervisorPolicy(
    max_restarts=3, window_s=5, backoff_base_s=0.001, stall_timeout_s=0.1, watchdog_interval_s=0.01
)


def registry() -> SchemaRegistry:
    r = SchemaRegistry()
    r.register(WORK)
    r.register(ECHO)
    return r


Behaviour = Callable[[Envelope, ActorContext], Awaitable[None]]


class Scripted(Actor):
    accepts = frozenset({"work"})

    def __init__(self, fn: Behaviour) -> None:
        self.fn = fn

    async def handle(self, msg: Envelope, ctx: ActorContext) -> None:
        await self.fn(msg, ctx)


def run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(asyncio.wait_for(coro, 20))


def mesh(**kw: object) -> AgentMesh:
    return AgentMesh(registry=registry(), policy=FAST, **kw)  # type: ignore[arg-type]


def test_crash_restarts_actor_and_redelivers_inflight_message() -> None:
    done: list[int] = []
    instances: list[int] = []

    async def go() -> None:
        async with mesh() as m:
            def factory() -> Actor:
                instances.append(1)

                async def fn(msg: Envelope, ctx: ActorContext) -> None:
                    if msg.payload["n"] == 2 and msg.attempt == 0:
                        raise RuntimeError("boom")
                    done.append(int(msg.payload["n"]))  # type: ignore[arg-type]

                return Scripted(fn)

            m.spawn("w", factory)
            for i in range(4):
                await m.send("test", "w", "work", {"n": i})
            await m.quiesce()
            assert m.cell("w").status is CellStatus.RUNNING
            tel = m.telemetry.snapshot()
            assert tel["actor.crashed"] == 1 and tel["actor.restarted"] == 1

    run(go())
    assert done == [0, 1, 2, 3]  # nothing lost, order preserved
    assert len(instances) == 2  # restart used a fresh instance


def test_poison_message_is_dead_lettered_not_crash_looped() -> None:
    processed: list[int] = []

    async def go() -> None:
        policy = SupervisorPolicy(
            max_restarts=10, window_s=5, backoff_base_s=0.001, poison_threshold=3,
            watchdog_interval_s=0.01,
        )
        async with AgentMesh(registry=registry(), policy=policy) as m:
            async def fn(msg: Envelope, ctx: ActorContext) -> None:
                if msg.payload["n"] == 13:
                    raise ValueError("poison")
                processed.append(int(msg.payload["n"]))  # type: ignore[arg-type]

            m.spawn("w", lambda: Scripted(fn))
            for n in (1, 13, 2):
                await m.send("test", "w", "work", {"n": n})
            await m.quiesce()
            dl = m.supervisor.dead_letters.drain()
            assert len(dl) == 1 and "poison after 3" in dl[0].reason
            assert dl[0].envelope is not None and dl[0].envelope.payload == {"n": 13}

    run(go())
    assert processed == [1, 2]


def test_restart_intensity_exceeded_escalates_without_killing_mesh() -> None:
    async def go() -> None:
        policy = SupervisorPolicy(
            max_restarts=2, window_s=10, backoff_base_s=0.001, poison_threshold=99,
            watchdog_interval_s=0.01,
        )
        async with AgentMesh(registry=registry(), policy=policy) as m:
            async def always(msg: Envelope, ctx: ActorContext) -> None:
                raise RuntimeError("always")

            ok: list[int] = []

            async def healthy(msg: Envelope, ctx: ActorContext) -> None:
                ok.append(1)

            m.spawn("bad", lambda: Scripted(always))
            m.spawn("good", lambda: Scripted(healthy))
            await m.send("t", "bad", "work", {"n": 1})
            for _ in range(200):
                if m.cell("bad").status is CellStatus.FAILED:
                    break
                await asyncio.sleep(0.01)
            assert m.cell("bad").status is CellStatus.FAILED
            assert m.telemetry.snapshot()["actor.escalated"] == 1
            with pytest.raises(EscalationError):
                await m.send("t", "bad", "work", {"n": 2})
            await m.send("t", "good", "work", {"n": 3})
            await m.quiesce()
            assert ok == [1]

    run(go())


def test_watchdog_detects_stalled_handler_and_recovers() -> None:
    handled: list[int] = []

    async def go() -> None:
        async with mesh() as m:
            async def fn(msg: Envelope, ctx: ActorContext) -> None:
                if msg.attempt == 0 and msg.payload["n"] == 1:
                    await asyncio.Event().wait()  # deadlock: waits forever
                handled.append(int(msg.payload["n"]))  # type: ignore[arg-type]

            m.spawn("w", lambda: Scripted(fn))
            await m.send("t", "w", "work", {"n": 1})
            await m.send("t", "w", "work", {"n": 2})
            await m.quiesce(timeout=5)
            assert m.telemetry.snapshot()["watchdog.deadlock"] >= 1

    run(go())
    assert handled == [1, 2]


def test_ask_deadline_lets_watchdog_reclaim_abandoned_work() -> None:
    async def go() -> None:
        policy = SupervisorPolicy(stall_timeout_s=60, watchdog_interval_s=0.01, backoff_base_s=0.001)
        async with AgentMesh(registry=registry(), policy=policy) as m:
            async def fn(msg: Envelope, ctx: ActorContext) -> None:
                await asyncio.sleep(10)

            m.spawn("w", lambda: Scripted(fn))
            with pytest.raises(AskTimeoutError):
                await m.ask("t", "w", "work", {"n": 1}, timeout=0.05)
            for _ in range(100):
                if m.telemetry.snapshot().get("watchdog.deadlock"):
                    break
                await asyncio.sleep(0.01)
            ev = m.telemetry.memory().of(EventKind.DEADLOCK_DETECTED)  # type: ignore[union-attr]
            assert ev and ev[0].attrs["deadline_exceeded"] is True

    run(go())


def test_duplicates_and_reordering_still_yield_exactly_once_effects() -> None:
    seen: list[int] = []

    async def go() -> None:
        chaos = ChaosTransport(ChaosConfig(duplicate=0.6, delay=0.5, seed=5))
        async with AgentMesh(registry=registry(), transport=chaos, policy=FAST) as m:
            async def fn(msg: Envelope, ctx: ActorContext) -> None:
                seen.append(int(msg.payload["n"]))  # type: ignore[arg-type]

            m.spawn("w", lambda: Scripted(fn))
            for i in range(50):
                await m.send("t", "w", "work", {"n": i})
            await chaos.flush()
            await m.quiesce()
            assert chaos.duplicated > 0
            assert m.telemetry.snapshot().get("message.duplicate", 0) >= 1

    run(go())
    assert sorted(seen) == list(range(50))


def test_malformed_and_drifted_payloads_are_dead_lettered() -> None:
    async def go() -> None:
        chaos = ChaosTransport(ChaosConfig(corrupt=1.0, seed=1))
        async with AgentMesh(registry=registry(), transport=chaos, policy=FAST) as m:
            async def fn(msg: Envelope, ctx: ActorContext) -> None:
                raise AssertionError("must never run")

            m.spawn("w", lambda: Scripted(fn))
            await m.send("t", "w", "work", {"n": 1})
            assert any("malformed" in d.reason for d in m.supervisor.dead_letters.drain())

        async with mesh() as m2:
            m2.spawn("w", lambda: Scripted(fn))
            with pytest.raises(SchemaError):  # sender-side fail fast
                await m2.send("t", "w", "work", {"n": "one"})
            await m2.send("t", "w", "echo", {"n": 1})  # valid schema, wrong topic for actor
            await m2.quiesce()
            reasons = [d.reason for d in m2.supervisor.dead_letters.drain()]
            assert any("not accepted" in r for r in reasons)

    run(go())


def test_schema_drift_at_receiver_after_producer_upgrade() -> None:
    async def go() -> None:
        reg = registry()
        async with AgentMesh(registry=reg, policy=FAST) as m:
            got: list[Envelope] = []

            async def fn(msg: Envelope, ctx: ActorContext) -> None:
                got.append(msg)

            m.spawn("w", lambda: Scripted(fn))
            # A v2 is registered with an upcaster: v1 messages already in flight are migrated.
            reg.register(
                Schema("work", 2, (Field("n", Kind.INT), Field("src", Kind.STR))),
                upcast_from_previous=lambda p: {**p, "src": "legacy"},
            )
            raw = Envelope("work", 1, "t", "w", m.clock.now(), {"n": 7})
            await m.transport.send(raw.to_wire())
            # A message claiming a version that doesn't exist is dead-lettered, not crashed on.
            bogus = Envelope("work", 9, "t", "w", m.clock.now(), {"n": 8})
            await m.transport.send(bogus.to_wire())
            await m.quiesce()
            assert len(got) == 1 and got[0].schema_version == 2
            assert got[0].payload == {"n": 7, "src": "legacy"}
            assert m.cell("w").status is CellStatus.RUNNING
            assert len(m.supervisor.dead_letters) == 1

    run(go())


def test_backpressure_propagates_to_sender() -> None:
    async def go() -> None:
        async with mesh(send_timeout_s=0.05) as m:
            gate = asyncio.Event()

            async def fn(msg: Envelope, ctx: ActorContext) -> None:
                await gate.wait()

            m.spawn("slow", lambda: Scripted(fn), capacity=2, overflow=OverflowPolicy.REJECT)
            await m.send("t", "slow", "work", {"n": 0})  # taken in-flight
            await asyncio.sleep(0.01)
            await m.send("t", "slow", "work", {"n": 1})
            await m.send("t", "slow", "work", {"n": 2})
            with pytest.raises(ChannelFullError):
                await m.send("t", "slow", "work", {"n": 3})
            gate.set()
            await m.quiesce()

    run(go())


def test_ask_reply_roundtrip_and_timeout() -> None:
    class Echo(Actor):
        accepts = frozenset({"echo"})

        async def handle(self, msg: Envelope, ctx: ActorContext) -> None:
            n = msg.payload["n"]
            assert isinstance(n, int)
            if n >= 0:
                await ctx.reply(msg, "echo", {"n": n * 2})

    async def go() -> None:
        async with mesh() as m:
            m.spawn("echo", Echo)
            reply = await m.ask("t", "echo", "echo", {"n": 21}, timeout=1)
            assert reply.payload == {"n": 42}
            with pytest.raises(AskTimeoutError):
                await m.ask("t", "echo", "echo", {"n": -1}, timeout=0.05)

    run(go())


def test_replicated_state_converges_despite_lossy_gossip() -> None:
    async def go() -> None:
        chaos = ChaosTransport(ChaosConfig(drop=0.5, duplicate=0.3, delay=0.3, seed=9))
        async with AgentMesh(
            registry=registry(), transport=chaos, policy=FAST, anti_entropy_every=3
        ) as m:
            async def fn(msg: Envelope, ctx: ActorContext) -> None:
                n = msg.payload["n"]
                assert isinstance(n, int)
                ctx.state.set(f"k{n % 5}", n)

            for name in ("a", "b", "c"):
                m.spawn(name, lambda: Scripted(fn))
            for i in range(60):
                target = "abc"[i % 3]
                try:
                    await m.send("t", target, "work", {"n": i})
                except Exception:  # noqa: BLE001 — dropped sends are expected under chaos
                    pass
            await chaos.flush()
            for _ in range(200):
                if m.converged() and m.state("a").snapshot():
                    break
                await asyncio.sleep(0.01)
            assert chaos.dropped > 0
            assert m.converged()
            assert m.state("a").snapshot() == m.state("c").snapshot()

    run(go())


def test_telemetry_sink_failure_never_breaks_engine() -> None:
    class Broken:
        def emit(self, event: object) -> None:
            raise OSError("disk full")

    async def go() -> None:
        tel = Telemetry(Broken())  # type: ignore[arg-type]
        async with AgentMesh(registry=registry(), telemetry=tel, policy=FAST) as m:
            async def fn(msg: Envelope, ctx: ActorContext) -> None:
                return None

            m.spawn("w", lambda: Scripted(fn))
            await m.send("t", "w", "work", {"n": 1})
            await m.quiesce()
        assert tel.sink_failures > 0

    run(go())
