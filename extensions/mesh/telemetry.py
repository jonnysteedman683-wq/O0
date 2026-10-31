"""Structured telemetry with fail-safe fan-out.

Telemetry is a side channel: a broken sink must never break the engine. ``Telemetry.emit``
swallows sink failures (counting them), keeps per-kind counters, and timestamps events with
the monotonic clock for durations and wall clock for correlation.

Telemetry is also the feedback loop: the supervisor and tool runtime both read counters
(e.g. ``rate_limited`` in the last window) to decide when to shed load.
"""

from __future__ import annotations

import json
import time
from collections import Counter, deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from .jsontypes import JSONObject, JSONValue


class EventKind(StrEnum):
    ACTOR_STARTED = "actor.started"
    ACTOR_STOPPED = "actor.stopped"
    ACTOR_CRASHED = "actor.crashed"
    ACTOR_RESTARTED = "actor.restarted"
    ACTOR_ESCALATED = "actor.escalated"
    DEADLOCK_DETECTED = "watchdog.deadlock"
    BACKPRESSURE = "watchdog.backpressure"
    DEGRADED = "watchdog.degraded"
    DEAD_LETTER = "message.dead_letter"
    DUPLICATE_DROPPED = "message.duplicate"
    MESSAGE_DROPPED = "message.dropped"
    SCHEMA_REJECTED = "schema.rejected"
    TOOL_CALL = "tool.call"
    TOOL_RETRY = "tool.retry"
    TOOL_MUTATED = "tool.mutated"
    TOOL_FALLBACK = "tool.fallback"
    TOOL_FAILED = "tool.failed"
    RATE_LIMITED = "tool.rate_limited"
    CIRCUIT_OPENED = "circuit.opened"
    CIRCUIT_CLOSED = "circuit.closed"
    ROLLBACK = "tx.rollback"
    SUBTASK_DONE = "plan.subtask"
    PLAN_DONE = "plan.done"
    STATE_SYNC = "state.sync"


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    kind: EventKind
    source: str
    attrs: JSONObject
    wall_ms: int = field(default_factory=lambda: time.time_ns() // 1_000_000)
    mono_s: float = field(default_factory=time.monotonic)

    def to_json(self) -> JSONObject:
        return {"kind": self.kind.value, "source": self.source, "wall_ms": self.wall_ms, **self.attrs}


class TelemetrySink(Protocol):
    def emit(self, event: TelemetryEvent) -> None: ...


class InMemorySink:
    """Bounded ring buffer; the default sink and the one tests assert against."""

    def __init__(self, capacity: int = 10_000) -> None:
        self.events: deque[TelemetryEvent] = deque(maxlen=capacity)

    def emit(self, event: TelemetryEvent) -> None:
        self.events.append(event)

    def of(self, kind: EventKind) -> list[TelemetryEvent]:
        return [e for e in self.events if e.kind is kind]


class JsonlSink:
    """Append-only JSONL file. Point it anywhere *except* ``state/`` (Hermes territory)."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: TelemetryEvent) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_json(), sort_keys=True) + "\n")


class Telemetry:
    def __init__(self, *sinks: TelemetrySink, window_s: float = 30.0) -> None:
        self.sinks: list[TelemetrySink] = list(sinks) or [InMemorySink()]
        self.counters: Counter[str] = Counter()
        self.sink_failures = 0
        self._window_s = window_s
        self._recent: deque[tuple[float, EventKind]] = deque(maxlen=50_000)

    def emit(self, kind: EventKind, source: str, **attrs: JSONValue) -> TelemetryEvent:
        event = TelemetryEvent(kind, source, dict(attrs))
        self.counters[kind.value] += 1
        self._recent.append((event.mono_s, kind))
        for sink in self.sinks:
            try:
                sink.emit(event)
            except Exception:  # noqa: BLE001 — telemetry must never take the engine down
                self.sink_failures += 1
        return event

    def rate(self, kind: EventKind, *, window_s: float | None = None) -> int:
        """Events of ``kind`` within the trailing window — the feedback-loop input."""
        cutoff = time.monotonic() - (window_s if window_s is not None else self._window_s)
        return sum(1 for t, k in self._recent if k is kind and t >= cutoff)

    def memory(self) -> InMemorySink | None:
        for s in self.sinks:
            if isinstance(s, InMemorySink):
                return s
        return None

    def snapshot(self) -> Mapping[str, int]:
        return dict(self.counters)
