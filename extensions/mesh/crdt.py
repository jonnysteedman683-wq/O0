"""Conflict-free replicated data types for decentralised mesh state.

There is no global mutable state in the engine: each node owns a ``StateReplica`` and
exchanges ``StateDelta`` events. Every merge here is commutative, associative, and
idempotent, so replicas converge under any delivery order, duplication, or partition-heal
sequence — no locks, no leader, no consensus round on the hot path.

Types:
  * ``GCounter`` / ``PNCounter`` — per-node counters (metrics, budgets, attempt tallies).
  * ``LWWMap`` — last-writer-wins map keyed by HLC timestamp, with tombstones for deletes.
  * ``StateReplica`` — an ``LWWMap`` bound to a clock that emits deltas for gossip.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass

from .clock import HLCTimestamp, HybridLogicalClock
from .errors import MalformedEnvelopeError
from .jsontypes import JSONObject, JSONValue


class GCounter:
    """Grow-only counter. ``merge`` takes the per-node maximum."""

    __slots__ = ("_counts",)

    def __init__(self, counts: Mapping[str, int] | None = None) -> None:
        self._counts: dict[str, int] = {}
        for node, n in (counts or {}).items():
            if n < 0:
                raise ValueError("GCounter entries must be non-negative")
            self._counts[node] = n

    def increment(self, node_id: str, amount: int = 1) -> None:
        if amount < 0:
            raise ValueError("GCounter only grows; use PNCounter to decrement")
        self._counts[node_id] = self._counts.get(node_id, 0) + amount

    @property
    def value(self) -> int:
        return sum(self._counts.values())

    def merge(self, other: GCounter) -> GCounter:
        keys = self._counts.keys() | other._counts.keys()
        return GCounter({k: max(self._counts.get(k, 0), other._counts.get(k, 0)) for k in keys})

    def to_dict(self) -> dict[str, int]:
        return dict(self._counts)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, GCounter) and self._counts == other._counts

    def __hash__(self) -> int:
        return hash(frozenset(self._counts.items()))


class PNCounter:
    """Increment/decrement counter built from two ``GCounter``s."""

    __slots__ = ("_pos", "_neg")

    def __init__(self, pos: GCounter | None = None, neg: GCounter | None = None) -> None:
        self._pos = pos or GCounter()
        self._neg = neg or GCounter()

    def increment(self, node_id: str, amount: int = 1) -> None:
        if amount >= 0:
            self._pos.increment(node_id, amount)
        else:
            self._neg.increment(node_id, -amount)

    def decrement(self, node_id: str, amount: int = 1) -> None:
        self.increment(node_id, -amount)

    @property
    def value(self) -> int:
        return self._pos.value - self._neg.value

    def merge(self, other: PNCounter) -> PNCounter:
        return PNCounter(self._pos.merge(other._pos), self._neg.merge(other._neg))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PNCounter) and (self._pos, self._neg) == (other._pos, other._neg)

    def __hash__(self) -> int:
        return hash((self._pos, self._neg))


@dataclass(frozen=True, slots=True)
class _Entry:
    ts: HLCTimestamp
    value: JSONValue
    deleted: bool


class LWWMap:
    """Last-writer-wins map. The entry with the greatest HLC timestamp wins; deletes are
    tombstones so a stale write can never resurrect a deleted key."""

    __slots__ = ("_entries",)

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}

    def _apply(self, key: str, entry: _Entry) -> bool:
        cur = self._entries.get(key)
        if cur is None or entry.ts > cur.ts:
            self._entries[key] = entry
            return True
        return False

    def set(self, key: str, value: JSONValue, ts: HLCTimestamp) -> bool:
        return self._apply(key, _Entry(ts, value, False))

    def delete(self, key: str, ts: HLCTimestamp) -> bool:
        return self._apply(key, _Entry(ts, None, True))

    def get(self, key: str, default: JSONValue = None) -> JSONValue:
        e = self._entries.get(key)
        return default if e is None or e.deleted else e.value

    def __contains__(self, key: object) -> bool:
        e = self._entries.get(key) if isinstance(key, str) else None
        return e is not None and not e.deleted

    def items(self) -> Iterator[tuple[str, JSONValue]]:
        for k in sorted(self._entries):
            e = self._entries[k]
            if not e.deleted:
                yield k, e.value

    def snapshot(self) -> JSONObject:
        return dict(self.items())

    def timestamp(self, key: str) -> HLCTimestamp | None:
        e = self._entries.get(key)
        return None if e is None else e.ts

    def deltas(self) -> Iterator[StateDelta]:
        """Every entry (tombstones included) as a delta — the anti-entropy payload."""
        for k in sorted(self._entries):
            e = self._entries[k]
            yield StateDelta(k, e.value, e.deleted, e.ts)

    def merge(self, other: LWWMap) -> LWWMap:
        out = LWWMap()
        for src in (self, other):
            for k, e in src._entries.items():
                out._apply(k, e)
        return out

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LWWMap) and self._entries == other._entries

    def __hash__(self) -> int:
        return hash(frozenset((k, e.ts) for k, e in self._entries.items()))


@dataclass(frozen=True, slots=True)
class StateDelta:
    """One replicated write. Idempotent to apply; safe to deliver more than once."""

    key: str
    value: JSONValue
    deleted: bool
    ts: HLCTimestamp

    def to_wire(self) -> JSONObject:
        return {"key": self.key, "value": self.value, "deleted": self.deleted, "ts": self.ts.encode()}

    @classmethod
    def from_wire(cls, raw: Mapping[str, JSONValue]) -> StateDelta:
        key, deleted, ts = raw.get("key"), raw.get("deleted"), raw.get("ts")
        if not isinstance(key, str) or not isinstance(deleted, bool) or not isinstance(ts, str):
            raise MalformedEnvelopeError(f"bad state delta {dict(raw)!r}")
        return cls(key, raw.get("value"), deleted, HLCTimestamp.decode(ts))


DeltaListener = Callable[[StateDelta], None]


class StateReplica:
    """A node-local replica of shared mesh state. Local writes are stamped with the node's
    HLC and published to listeners (the mesh gossip hub); remote deltas are merged and
    advance the local clock so subsequent local writes are causally after them."""

    def __init__(self, clock: HybridLogicalClock) -> None:
        self.clock = clock
        self._map = LWWMap()
        self._listeners: list[DeltaListener] = []
        self.applied = 0
        self.ignored = 0

    def subscribe(self, listener: DeltaListener) -> None:
        self._listeners.append(listener)

    def _publish(self, delta: StateDelta) -> None:
        for fn in self._listeners:
            fn(delta)

    def set(self, key: str, value: JSONValue) -> StateDelta:
        d = StateDelta(key, value, False, self.clock.now())
        self._map.set(key, value, d.ts)
        self._publish(d)
        return d

    def delete(self, key: str) -> StateDelta:
        d = StateDelta(key, None, True, self.clock.now())
        self._map.delete(key, d.ts)
        self._publish(d)
        return d

    def apply(self, delta: StateDelta) -> bool:
        """Merge a remote delta. Returns True if it changed local state."""
        self.clock.update(delta.ts)
        changed = (
            self._map.delete(delta.key, delta.ts)
            if delta.deleted
            else self._map.set(delta.key, delta.value, delta.ts)
        )
        if changed:
            self.applied += 1
        else:
            self.ignored += 1
        return changed

    def merge_from(self, other: LWWMap) -> int:
        """Full-state anti-entropy merge. Returns the number of entries that changed."""
        return sum(1 for d in other.deltas() if self.apply(d))

    def get(self, key: str, default: JSONValue = None) -> JSONValue:
        return self._map.get(key, default)

    def snapshot(self) -> JSONObject:
        return self._map.snapshot()

    @property
    def state(self) -> LWWMap:
        return self._map
