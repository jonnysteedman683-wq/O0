"""Async resilience primitives: circuit breaker, shared rate-limit bucket, cost budget,
and retry policy with deterministic jittered backoff.

These complement (do not replace) the synchronous 4-tier ``extensions.circuit`` breaker:
that one guards a single synchronous call; these guard *shared* resources across many
concurrent async callers, which is where cascades actually happen.

Rate-limit cascade prevention: when any caller receives ``RateLimitedError(retry_after)``,
``TokenBucket.penalize`` freezes the whole bucket until ``retry_after`` elapses. Every other
concurrent caller then waits once, instead of each hammering the upstream, each receiving
its own 429, and each retrying in lockstep.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from .errors import BudgetExceededError, CircuitOpenError

Clock = Callable[[], float]


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Classic three-state breaker.

    CLOSED --(failure_threshold consecutive failures)--> OPEN
    OPEN --(recovery_s elapsed)--> HALF_OPEN (admits ``half_open_probes`` trial calls)
    HALF_OPEN --success--> CLOSED ; --failure--> OPEN (timer restarts)
    """

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        recovery_s: float = 10.0,
        half_open_probes: int = 1,
        clock: Clock = time.monotonic,
        on_transition: Callable[[str, BreakerState, BreakerState], None] | None = None,
    ) -> None:
        self.name = name
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_s = recovery_s
        self.half_open_probes = max(1, half_open_probes)
        self._clock = clock
        self._on_transition = on_transition
        self._state = BreakerState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._probes_in_flight = 0

    @property
    def state(self) -> BreakerState:
        if self._state is BreakerState.OPEN and self._clock() - self._opened_at >= self.recovery_s:
            self._transition(BreakerState.HALF_OPEN)
            self._probes_in_flight = 0
        return self._state

    def _transition(self, new: BreakerState) -> None:
        old, self._state = self._state, new
        if old is not new and self._on_transition is not None:
            self._on_transition(self.name, old, new)

    def acquire(self) -> None:
        """Raise ``CircuitOpenError`` if the call must not proceed."""
        s = self.state
        if s is BreakerState.OPEN:
            raise CircuitOpenError(f"{self.name}: circuit open")
        if s is BreakerState.HALF_OPEN:
            if self._probes_in_flight >= self.half_open_probes:
                raise CircuitOpenError(f"{self.name}: half-open probe in flight")
            self._probes_in_flight += 1

    def record_success(self) -> None:
        self._failures = 0
        if self._state is not BreakerState.CLOSED:
            self._transition(BreakerState.CLOSED)
        self._probes_in_flight = 0

    def record_failure(self) -> None:
        self._failures += 1
        if self._state is BreakerState.HALF_OPEN or self._failures >= self.failure_threshold:
            self._opened_at = self._clock()
            self._probes_in_flight = 0
            self._transition(BreakerState.OPEN)

    def release_probe(self) -> None:
        """Called when a half-open probe ends without a verdict (e.g. cancelled)."""
        self._probes_in_flight = max(0, self._probes_in_flight - 1)


class TokenBucket:
    """Async token bucket with a shared penalty window for upstream rate limits."""

    def __init__(
        self,
        rate_per_s: float,
        burst: int,
        *,
        clock: Clock = time.monotonic,
        sleep: Callable[[float], object] | None = None,
    ) -> None:
        if rate_per_s <= 0 or burst < 1:
            raise ValueError("rate_per_s must be > 0 and burst >= 1")
        self.rate = rate_per_s
        self.burst = burst
        self._tokens = float(burst)
        self._clock = clock
        self._last = clock()
        self._frozen_until = 0.0
        self._lock = asyncio.Lock()
        self.penalties = 0

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self.burst, self._tokens + (now - self._last) * self.rate)
        self._last = now

    def penalize(self, retry_after_s: float) -> None:
        """Freeze the bucket for everyone until ``retry_after_s`` from now."""
        until = self._clock() + retry_after_s
        if until > self._frozen_until:
            self._frozen_until = until
            self._tokens = 0.0
            self._last = until
            self.penalties += 1

    def wait_time(self) -> float:
        now = self._clock()
        if now < self._frozen_until:
            return self._frozen_until - now
        self._refill()
        return 0.0 if self._tokens >= 1 else (1 - self._tokens) / self.rate

    async def acquire(self, *, max_wait_s: float | None = None) -> float:
        """Take one token, sleeping as needed. Returns seconds waited."""
        waited = 0.0
        async with self._lock:  # FIFO fairness among waiters
            while True:
                w = self.wait_time()
                if w <= 0:
                    self._tokens -= 1
                    return waited
                if max_wait_s is not None and waited + w > max_wait_s:
                    raise TimeoutError(f"rate limit wait {w:.3f}s exceeds {max_wait_s}s")
                await asyncio.sleep(w)
                waited += w


class CostBudget:
    """Reserve-then-commit cost accounting so concurrent calls cannot jointly overspend."""

    def __init__(self, limit: float) -> None:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        self.limit = limit
        self.spent = 0.0
        self.reserved = 0.0

    @property
    def remaining(self) -> float:
        return self.limit - self.spent - self.reserved

    def reserve(self, amount: float) -> None:
        if amount > self.remaining + 1e-12:
            raise BudgetExceededError(
                f"cost {amount:.4f} exceeds remaining budget {self.remaining:.4f}"
            )
        self.reserved += amount

    def commit(self, reserved: float, actual: float | None = None) -> None:
        self.reserved = max(0.0, self.reserved - reserved)
        self.spent += reserved if actual is None else actual

    def refund(self, reserved: float) -> None:
        self.reserved = max(0.0, self.reserved - reserved)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 0.05
    max_delay_s: float = 2.0
    multiplier: float = 2.0
    jitter: float = 0.2  # +/- fraction
    seed: int | None = 0  # deterministic by default; None for system entropy

    def delays(self) -> list[float]:
        """Backoff schedule between attempts (len == max_attempts - 1)."""
        rng = random.Random(self.seed)
        out: list[float] = []
        d = self.base_delay_s
        for _ in range(max(0, self.max_attempts - 1)):
            j = 1 + rng.uniform(-self.jitter, self.jitter)
            out.append(min(self.max_delay_s, max(0.0, d * j)))
            d *= self.multiplier
        return out
