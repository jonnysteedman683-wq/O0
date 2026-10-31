"""Exception taxonomy for the mesh engine.

The split between *transient* and *permanent* failures drives every recovery decision:
transient errors are retried (with backoff and parameter mutation), permanent errors go
straight to fallback or dead-letter. Nothing in the engine catches bare ``Exception`` to
hide it: unknown exceptions are classified as transient once, then surfaced in telemetry.
"""

from __future__ import annotations

from collections.abc import Sequence


class MeshError(Exception):
    """Root of every error raised by ``extensions.mesh``."""


# --- schema / payload -------------------------------------------------------------------------


class SchemaError(MeshError):
    """A payload does not match its declared schema."""

    def __init__(self, schema: str, violations: Sequence[str]) -> None:
        self.schema = schema
        self.violations: tuple[str, ...] = tuple(violations)
        super().__init__(f"{schema}: " + "; ".join(self.violations))


class UnknownSchemaError(MeshError):
    """No schema is registered under the requested name/version."""


class MalformedEnvelopeError(MeshError):
    """A wire message could not be decoded into an ``Envelope``."""


# --- clock ------------------------------------------------------------------------------------


class ClockDriftError(MeshError):
    """A remote timestamp is further ahead of local physical time than allowed."""


# --- channels ---------------------------------------------------------------------------------


class ChannelClosedError(MeshError):
    """Send on a closed channel, or receive on a closed and drained channel."""


class ChannelFullError(MeshError):
    """A ``REJECT``-policy channel is at capacity."""


class BackpressureTimeoutError(MeshError):
    """A ``BLOCK``-policy send waited longer than its timeout for capacity."""


# --- actors / supervision ---------------------------------------------------------------------


class ActorNotFoundError(MeshError):
    """A message was addressed to an actor the mesh does not know."""


class AskTimeoutError(MeshError):
    """A request/reply ``ask`` received no reply before its deadline."""


class EscalationError(MeshError):
    """An actor exceeded its restart intensity and was taken out of service."""


# --- tools ------------------------------------------------------------------------------------


class ToolError(MeshError):
    """Base for tool failures. ``transient`` decides whether a retry is worthwhile."""

    transient: bool = True


class TransientToolError(ToolError):
    transient = True


class PermanentToolError(ToolError):
    transient = False


class ToolTimeoutError(TransientToolError):
    """The tool exceeded its timeout and was cancelled (or its process killed)."""


class RateLimitedError(TransientToolError):
    """The tool (or its upstream) signalled a rate limit; ``retry_after_s`` is a hint."""

    def __init__(self, message: str = "rate limited", *, retry_after_s: float = 1.0) -> None:
        super().__init__(message)
        self.retry_after_s = max(0.0, retry_after_s)


class ToolOutputDriftError(PermanentToolError):
    """A tool returned output that violates its declared output schema."""


class CircuitOpenError(TransientToolError):
    """The tool's circuit breaker is open; the call was not attempted."""


class BudgetExceededError(PermanentToolError):
    """Executing the call would exceed the caller's cost budget."""


class NoRouteError(PermanentToolError):
    """No registered tool can serve the requested capability within budget."""


class RollbackError(MeshError):
    """One or more compensations failed while rolling back a transaction."""

    def __init__(self, failures: Sequence[str]) -> None:
        self.failures: tuple[str, ...] = tuple(failures)
        super().__init__("rollback incomplete: " + "; ".join(self.failures))


# --- orchestration ----------------------------------------------------------------------------


class PlanError(MeshError):
    """A task plan is structurally invalid (cycle, missing dependency, duplicate id)."""
