"""Hybrid Logical Clock (Kulkarni et al., 2014).

HLC timestamps give a total order over events across nodes that (a) respects causality
(send happens-before receive) and (b) stays within a bounded distance of physical time.
They are the ordering key for every CRDT write and every envelope in the mesh, so two
replicas that see the same set of events always converge to the same state regardless of
delivery order.

Invariants:
  * ``now()`` and ``update()`` are strictly monotonic per clock instance.
  * ``update(remote)`` returns a timestamp greater than both the local last and ``remote``.
  * A remote timestamp more than ``max_drift_ms`` ahead of local physical time is rejected
    (``ClockDriftError``) instead of dragging the whole mesh into the future.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .errors import ClockDriftError, MalformedEnvelopeError


def _wall_ms() -> int:
    return time.time_ns() // 1_000_000


@dataclass(frozen=True, order=True, slots=True)
class HLCTimestamp:
    """Totally ordered: (wall_ms, logical, node_id). ``node_id`` breaks exact ties."""

    wall_ms: int
    logical: int
    node_id: str

    def encode(self) -> str:
        return f"{self.wall_ms:015d}.{self.logical:06d}.{self.node_id}"

    @classmethod
    def decode(cls, raw: str) -> HLCTimestamp:
        parts = raw.split(".", 2)
        if len(parts) != 3 or not parts[2]:
            raise MalformedEnvelopeError(f"bad HLC timestamp {raw!r}")
        try:
            return cls(int(parts[0]), int(parts[1]), parts[2])
        except ValueError as exc:
            raise MalformedEnvelopeError(f"bad HLC timestamp {raw!r}") from exc


class HybridLogicalClock:
    """Thread-safe HLC. Inject ``physical_ms`` for deterministic tests."""

    def __init__(
        self,
        node_id: str,
        *,
        physical_ms: Callable[[], int] = _wall_ms,
        max_drift_ms: int = 60_000,
    ) -> None:
        if not node_id or "." in node_id:
            raise ValueError("node_id must be non-empty and contain no '.'")
        self.node_id = node_id
        self._physical = physical_ms
        self._max_drift = max_drift_ms
        self._wall = 0
        self._logical = 0
        self._lock = threading.Lock()

    def now(self) -> HLCTimestamp:
        """Timestamp a local or send event."""
        with self._lock:
            pt = self._physical()
            if pt > self._wall:
                self._wall, self._logical = pt, 0
            else:
                self._logical += 1
            return HLCTimestamp(self._wall, self._logical, self.node_id)

    def update(self, remote: HLCTimestamp) -> HLCTimestamp:
        """Merge a received timestamp and timestamp the receive event."""
        with self._lock:
            pt = self._physical()
            if remote.wall_ms - pt > self._max_drift:
                raise ClockDriftError(
                    f"remote {remote.node_id} is {remote.wall_ms - pt}ms ahead "
                    f"(max {self._max_drift}ms)"
                )
            wall = max(self._wall, remote.wall_ms, pt)
            if wall == self._wall == remote.wall_ms:
                logical = max(self._logical, remote.logical) + 1
            elif wall == self._wall:
                logical = self._logical + 1
            elif wall == remote.wall_ms:
                logical = remote.logical + 1
            else:
                logical = 0
            self._wall, self._logical = wall, logical
            return HLCTimestamp(wall, logical, self.node_id)

    def peek(self) -> HLCTimestamp:
        with self._lock:
            return HLCTimestamp(self._wall, self._logical, self.node_id)
