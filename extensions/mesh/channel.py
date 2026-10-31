"""Bounded asynchronous channels with explicit backpressure.

Unbounded queues turn overload into memory exhaustion; every mailbox in the mesh is a
``BoundedChannel`` with a declared ``OverflowPolicy``:

  * ``BLOCK`` — the sender awaits capacity (optionally with a timeout). Backpressure
    propagates upstream naturally through ``await``.
  * ``REJECT`` — the send fails fast with ``ChannelFullError``; the caller decides.
  * ``DROP_OLDEST`` — the oldest queued item is evicted (counted, reported to ``on_drop``).
    Use for telemetry-like streams where freshness beats completeness.

``push_front`` lets a supervisor requeue an in-flight message ahead of the backlog after a
crash, ignoring capacity, so a restart never loses or reorders the message being processed.

Implementation note: waiters are plain futures (the ``asyncio.Queue`` technique), so the
sync paths (``try_send``, ``push_front``, ``close``) can wake receivers without a lock, and a
waiter cancelled after being woken hands its wake-up to the next waiter (no lost wake-ups).
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

from .errors import BackpressureTimeoutError, ChannelClosedError, ChannelFullError

T = TypeVar("T")


class OverflowPolicy(StrEnum):
    BLOCK = "block"
    REJECT = "reject"
    DROP_OLDEST = "drop_oldest"


@dataclass(slots=True)
class ChannelStats:
    sent: int = 0
    received: int = 0
    dropped: int = 0
    rejected: int = 0
    blocked_waits: int = 0
    high_watermark: int = 0


def _wake_one(waiters: deque[asyncio.Future[None]]) -> None:
    while waiters:
        w = waiters.popleft()
        if not w.done():
            w.set_result(None)
            return


def _wake_all(waiters: deque[asyncio.Future[None]]) -> None:
    while waiters:
        w = waiters.popleft()
        if not w.done():
            w.set_result(None)


async def _wait(
    waiters: deque[asyncio.Future[None]],
    deadline: float | None,
    on_lost_wakeup: Callable[[], None],
) -> bool:
    """Park on a fresh future. Returns False on timeout."""
    fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    waiters.append(fut)
    remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
    try:
        await asyncio.wait_for(asyncio.shield(fut), remaining)
        return True
    except TimeoutError:
        return False
    except asyncio.CancelledError:
        if fut.done() and not fut.cancelled():
            on_lost_wakeup()  # we were woken but won't act on it: pass it on
        raise
    finally:
        if not fut.done():
            fut.cancel()
        try:
            waiters.remove(fut)
        except ValueError:
            pass


class BoundedChannel(Generic[T]):
    def __init__(
        self,
        capacity: int,
        *,
        policy: OverflowPolicy = OverflowPolicy.BLOCK,
        name: str = "channel",
        on_drop: Callable[[T], None] | None = None,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self.policy = policy
        self.name = name
        self._on_drop = on_drop
        self._buf: deque[T] = deque()
        self._getters: deque[asyncio.Future[None]] = deque()
        self._putters: deque[asyncio.Future[None]] = deque()
        self._closed = False
        self.stats = ChannelStats()

    def __len__(self) -> int:
        return len(self._buf)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def pressure(self) -> float:
        """Fill ratio — the watchdog's backpressure signal (can exceed 1 after push_front)."""
        return len(self._buf) / self.capacity

    def _enqueue(self, item: T, *, front: bool = False) -> None:
        if front:
            self._buf.appendleft(item)
        else:
            self._buf.append(item)
        self.stats.sent += 1
        self.stats.high_watermark = max(self.stats.high_watermark, len(self._buf))
        _wake_one(self._getters)

    async def send(self, item: T, *, timeout: float | None = None) -> None:
        deadline = None if timeout is None else time.monotonic() + timeout
        waited = False
        while True:
            if self._closed:
                raise ChannelClosedError(self.name)
            if len(self._buf) < self.capacity:
                break
            if self.policy is OverflowPolicy.REJECT:
                self.stats.rejected += 1
                raise ChannelFullError(f"{self.name} full ({self.capacity})")
            if self.policy is OverflowPolicy.DROP_OLDEST:
                dropped = self._buf.popleft()
                self.stats.dropped += 1
                if self._on_drop is not None:
                    self._on_drop(dropped)
                continue
            if not waited:
                self.stats.blocked_waits += 1
                waited = True
            if not await _wait(self._putters, deadline, lambda: _wake_one(self._putters)):
                raise BackpressureTimeoutError(f"{self.name}: no capacity after {timeout}s")
        self._enqueue(item)

    def try_send(self, item: T) -> bool:
        """Non-blocking send. Never evicts; returns False when full or closed."""
        if self._closed:
            return False
        if len(self._buf) >= self.capacity:
            self.stats.rejected += 1
            return False
        self._enqueue(item)
        return True

    def offer(self, item: T) -> bool:
        """Sync send honouring ``DROP_OLDEST`` (evicts); other policies behave like try_send."""
        if self.policy is OverflowPolicy.DROP_OLDEST and not self._closed:
            while len(self._buf) >= self.capacity:
                dropped = self._buf.popleft()
                self.stats.dropped += 1
                if self._on_drop is not None:
                    self._on_drop(dropped)
        return self.try_send(item)

    def push_front(self, item: T) -> None:
        """Requeue ahead of the backlog, bypassing capacity (supervisor redelivery)."""
        if self._closed:
            raise ChannelClosedError(self.name)
        self._enqueue(item, front=True)

    async def recv(self, *, timeout: float | None = None) -> T:
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self._buf:
            if self._closed:
                raise ChannelClosedError(self.name)
            if not await _wait(self._getters, deadline, lambda: _wake_one(self._getters)):
                raise TimeoutError(f"{self.name}: recv timed out after {timeout}s")
        item = self._buf.popleft()
        self.stats.received += 1
        _wake_one(self._putters)
        return item

    def drain(self) -> list[T]:
        items = list(self._buf)
        self._buf.clear()
        _wake_all(self._putters)
        return items

    def close(self) -> None:
        """Stop accepting sends. Receivers drain what is queued, then get ChannelClosedError."""
        self._closed = True
        _wake_all(self._getters)
        _wake_all(self._putters)

    async def __aiter__(self) -> AsyncIterator[T]:
        while True:
            try:
                yield await self.recv()
            except ChannelClosedError:
                return
