"""Transport adapters. The engine only ever hands a transport plain JSON (``Envelope.to_wire``)
and receives plain JSON back, so swapping loopback for a socket/RPC transport cannot change
engine semantics.

  * ``LoopbackTransport`` — in-process; still round-trips through ``json`` so nothing that
    is not wire-safe can sneak between actors.
  * ``ChaosTransport`` — seeded drop / duplicate / delay(reorder) / corrupt injection for
    fault-tolerance tests. Deterministic for a given seed.

A network adapter (e.g. over ``extensions.synapse.net_bridge``) implements the same
``Transport`` protocol: ``bind`` the inbound handler, ``send`` outbound wire dicts, ``close``.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from .jsontypes import JSONObject

Inbound = Callable[[object], Awaitable[None]]


class Transport(Protocol):
    def bind(self, inbound: Inbound) -> None: ...

    async def send(self, wire: JSONObject) -> None: ...

    async def close(self) -> None: ...


class LoopbackTransport:
    def __init__(self) -> None:
        self._inbound: Inbound | None = None

    def bind(self, inbound: Inbound) -> None:
        self._inbound = inbound

    async def _deliver(self, raw: object) -> None:
        if self._inbound is None:
            raise RuntimeError("transport not bound")
        await self._inbound(raw)

    async def send(self, wire: JSONObject) -> None:
        await self._deliver(json.loads(json.dumps(wire, allow_nan=False)))

    async def close(self) -> None:
        self._inbound = None


@dataclass(frozen=True, slots=True)
class ChaosConfig:
    drop: float = 0.0
    duplicate: float = 0.0
    delay: float = 0.0
    max_delay_s: float = 0.02
    corrupt: float = 0.0
    seed: int = 7
    spare_topics: frozenset[str] = frozenset()  # topics never perturbed (e.g. replies)


class ChaosTransport(LoopbackTransport):
    def __init__(self, config: ChaosConfig) -> None:
        super().__init__()
        self.config = config
        self._rng = random.Random(config.seed)
        self._pending: set[asyncio.Task[None]] = set()
        self.dropped = self.duplicated = self.delayed = self.corrupted = 0

    async def send(self, wire: JSONObject) -> None:
        c = self.config
        if wire.get("topic") in c.spare_topics:
            await super().send(wire)
            return
        if self._rng.random() < c.drop:
            self.dropped += 1
            return
        raw: object = json.loads(json.dumps(wire, allow_nan=False))
        if self._rng.random() < c.corrupt and isinstance(raw, dict):
            self.corrupted += 1
            raw.pop("msg_id", None)
            raw["payload"] = "<<garbled>>"
        copies = 2 if self._rng.random() < c.duplicate else 1
        self.duplicated += copies - 1
        for _ in range(copies):
            if self._rng.random() < c.delay:
                self.delayed += 1
                t = asyncio.get_running_loop().create_task(
                    self._later(raw, self._rng.uniform(0, c.max_delay_s))
                )
                self._pending.add(t)
                t.add_done_callback(self._pending.discard)
            else:
                await self._deliver(raw)

    async def _later(self, raw: object, delay: float) -> None:
        await asyncio.sleep(delay)
        try:
            await self._deliver(raw)
        except Exception:  # noqa: BLE001 — a late message hitting backpressure is just lost
            pass

    async def flush(self) -> None:
        while self._pending:
            await asyncio.gather(*list(self._pending), return_exceptions=True)

    async def close(self) -> None:
        for t in list(self._pending):
            t.cancel()
        await asyncio.gather(*list(self._pending), return_exceptions=True)
        await super().close()
