"""Bounded channels: backpressure policies, ordering, closure, and concurrency edge cases."""

from __future__ import annotations

import asyncio

import pytest

from extensions.mesh import (
    BackpressureTimeoutError,
    BoundedChannel,
    ChannelClosedError,
    ChannelFullError,
    OverflowPolicy,
)


def run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def test_block_policy_applies_backpressure_until_consumed() -> None:
    async def go() -> None:
        ch: BoundedChannel[int] = BoundedChannel(2)
        await ch.send(1)
        await ch.send(2)
        sender = asyncio.ensure_future(ch.send(3))
        await asyncio.sleep(0.01)
        assert not sender.done()  # blocked: channel full
        assert await ch.recv() == 1
        await asyncio.wait_for(sender, 1)
        assert [await ch.recv(), await ch.recv()] == [2, 3]
        assert ch.stats.blocked_waits == 1

    run(go())


def test_block_policy_timeout() -> None:
    async def go() -> None:
        ch: BoundedChannel[int] = BoundedChannel(1)
        await ch.send(1)
        with pytest.raises(BackpressureTimeoutError):
            await ch.send(2, timeout=0.02)
        assert len(ch) == 1

    run(go())


def test_reject_and_drop_oldest_policies() -> None:
    async def go() -> None:
        rej: BoundedChannel[int] = BoundedChannel(1, policy=OverflowPolicy.REJECT)
        await rej.send(1)
        with pytest.raises(ChannelFullError):
            await rej.send(2)
        dropped: list[int] = []
        drop: BoundedChannel[int] = BoundedChannel(
            2, policy=OverflowPolicy.DROP_OLDEST, on_drop=dropped.append
        )
        for i in range(5):
            await drop.send(i)
        assert dropped == [0, 1, 2] and drop.drain() == [3, 4]
        assert drop.offer(9) and drop.offer(10) and drop.offer(11)
        assert drop.drain() == [10, 11]

    run(go())


def test_close_drains_then_raises_and_wakes_blocked_senders() -> None:
    async def go() -> None:
        ch: BoundedChannel[int] = BoundedChannel(1)
        await ch.send(1)
        blocked = asyncio.ensure_future(ch.send(2))
        await asyncio.sleep(0)
        ch.close()
        with pytest.raises(ChannelClosedError):
            await blocked
        assert await ch.recv() == 1
        with pytest.raises(ChannelClosedError):
            await ch.recv()
        with pytest.raises(ChannelClosedError):
            await ch.send(3)

    run(go())


def test_push_front_requeues_ahead_of_backlog_even_when_full() -> None:
    async def go() -> None:
        ch: BoundedChannel[str] = BoundedChannel(2)
        await ch.send("b")
        await ch.send("c")
        ch.push_front("a")
        assert [await ch.recv() for _ in range(3)] == ["a", "b", "c"]

    run(go())


def test_many_producers_consumers_conserve_items_under_backpressure() -> None:
    async def go() -> None:
        ch: BoundedChannel[int] = BoundedChannel(3)
        got: list[int] = []

        async def produce(base: int) -> None:
            for i in range(100):
                await ch.send(base + i)

        async def consume() -> None:
            async for item in ch:
                got.append(item)
                if len(got) % 7 == 0:
                    await asyncio.sleep(0)

        consumers = [asyncio.ensure_future(consume()) for _ in range(4)]
        await asyncio.gather(*(produce(k * 1000) for k in range(5)))
        ch.close()
        await asyncio.gather(*consumers)
        assert sorted(got) == sorted(k * 1000 + i for k in range(5) for i in range(100))
        assert ch.stats.high_watermark <= 3

    run(go())


def test_cancelled_receiver_does_not_swallow_wakeup() -> None:
    async def go() -> None:
        ch: BoundedChannel[int] = BoundedChannel(4)
        r1 = asyncio.ensure_future(ch.recv())
        r2 = asyncio.ensure_future(ch.recv())
        await asyncio.sleep(0)
        assert ch.try_send(42)  # wakes r1...
        r1.cancel()  # ...which is cancelled before it runs
        assert await asyncio.wait_for(r2, 1) == 42  # wake-up handed to r2
        with pytest.raises(asyncio.CancelledError):
            await r1

    run(go())


def test_recv_timeout() -> None:
    async def go() -> None:
        ch: BoundedChannel[int] = BoundedChannel(1)
        with pytest.raises(TimeoutError):
            await ch.recv(timeout=0.01)

    run(go())
