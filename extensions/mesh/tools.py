"""Federated tool runtime: schema-checked, isolated, self-correcting, cost-aware.

One call path for every tool:

  validate input -> breaker gate -> budget reserve -> rate-limit token -> execute
  (in-process with timeout, or in a resource-limited ``python -I`` subprocess)
  -> validate output -> commit cost

Failure handling is deterministic and never terminates the caller with a raw exception:

  * transient (timeout, 5xx-like, rate limit) -> jittered backoff, then *parameter mutation*:
    registered ``ParamMutator``s propose new params from the error (e.g. halve a batch size,
    shorten a prompt, drop an optional flag) and the next attempt uses them.
  * rate limit -> the tool's shared ``TokenBucket`` is penalised so concurrent callers back
    off together (no cascade).
  * permanent / output drift / exhausted retries -> ``route()`` falls back to the next
    cheapest healthy tool advertising the same capability.
  * inside a ``Transaction`` -> any failure runs registered compensations in reverse order
    (localised rollback), and the original error is re-raised with rollback status attached.

Isolation honesty: ``subprocess_tool`` gives process, memory, CPU-time, and environment
isolation (``python -I``, scrubbed env, POSIX rlimits, hard kill on timeout). It is NOT a
security sandbox against hostile code — use a container/gVisor boundary for that.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import TracebackType

from .errors import (
    BudgetExceededError,
    CircuitOpenError,
    NoRouteError,
    PermanentToolError,
    RateLimitedError,
    RollbackError,
    SchemaError,
    ToolError,
    ToolOutputDriftError,
    ToolTimeoutError,
    TransientToolError,
)
from .resilience import BreakerState, CircuitBreaker, CostBudget, RetryPolicy, TokenBucket
from .schema import Schema
from .telemetry import EventKind, Telemetry
from .jsontypes import JSONObject, JSONValue

ToolFn = Callable[[JSONObject], Awaitable[JSONObject]]
Compensation = Callable[[JSONObject, JSONObject], Awaitable[None]]
ParamMutator = Callable[[JSONObject, ToolError, int], JSONObject | None]
CostEstimator = Callable[[JSONObject], float]


class Isolation(StrEnum):
    INPROC = "inproc"
    SUBPROCESS = "subprocess"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    input_schema: Schema
    output_schema: Schema
    capabilities: frozenset[str]
    cost_per_call: float = 0.0
    timeout_s: float = 10.0
    idempotent: bool = True
    isolation: Isolation = Isolation.INPROC
    rate_per_s: float | None = None
    burst: int = 1


@dataclass(slots=True)
class _Registered:
    spec: ToolSpec
    fn: ToolFn
    compensate: Compensation | None
    mutators: tuple[ParamMutator, ...]
    estimate: CostEstimator
    breaker: CircuitBreaker
    bucket: TokenBucket | None


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    tool: str
    ok: bool
    output: JSONObject
    attempts: int
    cost: float
    params: JSONObject  # the params that finally succeeded (post-mutation)
    error: str | None = None
    fallbacks: tuple[str, ...] = ()


@dataclass(slots=True)
class _Applied:
    tool: str
    params: JSONObject
    output: JSONObject
    compensate: Compensation


def _flat_cost(c: float) -> CostEstimator:
    def est(_params: JSONObject) -> float:
        return c

    return est


class ToolRuntime:
    def __init__(
        self,
        *,
        telemetry: Telemetry | None = None,
        retry: RetryPolicy = RetryPolicy(),
        breaker_threshold: int = 3,
        breaker_recovery_s: float = 5.0,
    ) -> None:
        self.telemetry = telemetry or Telemetry()
        self.retry = retry
        self._breaker_threshold = breaker_threshold
        self._breaker_recovery_s = breaker_recovery_s
        self._tools: dict[str, _Registered] = {}

    # ---- registration --------------------------------------------------------------------

    def register(
        self,
        spec: ToolSpec,
        fn: ToolFn,
        *,
        compensate: Compensation | None = None,
        mutators: Sequence[ParamMutator] = (),
        estimate: CostEstimator | None = None,
    ) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool {spec.name!r} already registered")
        bucket = (
            TokenBucket(spec.rate_per_s, spec.burst) if spec.rate_per_s is not None else None
        )
        self._tools[spec.name] = _Registered(
            spec=spec,
            fn=fn,
            compensate=compensate,
            mutators=tuple(mutators),
            estimate=estimate or _flat_cost(spec.cost_per_call),
            breaker=CircuitBreaker(
                spec.name,
                failure_threshold=self._breaker_threshold,
                recovery_s=self._breaker_recovery_s,
                on_transition=self._on_breaker,
            ),
            bucket=bucket,
        )

    def _on_breaker(self, name: str, old: BreakerState, new: BreakerState) -> None:
        kind = EventKind.CIRCUIT_OPENED if new is BreakerState.OPEN else EventKind.CIRCUIT_CLOSED
        if new is not BreakerState.HALF_OPEN:
            self.telemetry.emit(kind, name, old=old.value, new=new.value)

    def spec(self, name: str) -> ToolSpec:
        return self._get(name).spec

    def breaker(self, name: str) -> CircuitBreaker:
        return self._get(name).breaker

    def _get(self, name: str) -> _Registered:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise NoRouteError(f"unknown tool {name!r}") from exc

    # ---- single tool ---------------------------------------------------------------------

    async def invoke(
        self, name: str, params: Mapping[str, object], *, budget: CostBudget | None = None
    ) -> ToolOutcome:
        """Run one tool with retries + mutation. Never raises for tool failures: the outcome
        carries ``ok=False`` and the error. Raises only for caller errors (unknown tool)."""
        reg = self._get(name)
        try:
            current = reg.spec.input_schema.validate(params)
        except SchemaError as exc:
            self.telemetry.emit(EventKind.SCHEMA_REJECTED, name, where="input", error=str(exc))
            return ToolOutcome(name, False, {}, 0, 0.0, {}, error=f"input: {exc}")

        delays = self.retry.delays()
        attempts = 0
        last: ToolError | None = None
        spent = 0.0
        while attempts < self.retry.max_attempts:
            attempts += 1
            try:
                out, cost = await self._attempt(reg, current, budget)
                spent += cost
                return ToolOutcome(name, True, out, attempts, spent, current)
            except ToolError as err:
                last = err
                if isinstance(err, RateLimitedError):
                    self.telemetry.emit(
                        EventKind.RATE_LIMITED, name, retry_after_s=err.retry_after_s
                    )
                    if reg.bucket is not None:
                        reg.bucket.penalize(err.retry_after_s)
                if not err.transient or attempts >= self.retry.max_attempts:
                    break
                # A non-idempotent tool is only retried when the call provably never ran.
                if not reg.spec.idempotent and not isinstance(
                    err, (CircuitOpenError, RateLimitedError)
                ):
                    break
                mutated = self._mutate(reg, current, err, attempts)
                if mutated is not None:
                    current = mutated
                delay = delays[attempts - 1] if attempts - 1 < len(delays) else 0.0
                if isinstance(err, RateLimitedError) and reg.bucket is None:
                    delay = max(delay, err.retry_after_s)
                self.telemetry.emit(
                    EventKind.TOOL_RETRY, name, attempt=attempts, delay_s=delay, error=str(err)
                )
                await asyncio.sleep(delay)
        assert last is not None
        self.telemetry.emit(EventKind.TOOL_FAILED, name, attempts=attempts, error=str(last))
        return ToolOutcome(name, False, {}, attempts, spent, current, error=f"{type(last).__name__}: {last}")

    def _mutate(
        self, reg: _Registered, params: JSONObject, err: ToolError, attempt: int
    ) -> JSONObject | None:
        for m in reg.mutators:
            proposal = m(dict(params), err, attempt)
            if proposal is None or proposal == params:
                continue
            try:
                valid = reg.spec.input_schema.validate(proposal)
            except SchemaError:
                continue  # a mutator may never smuggle an invalid payload through
            self.telemetry.emit(
                EventKind.TOOL_MUTATED,
                reg.spec.name,
                attempt=attempt,
                changed=list[JSONValue](sorted(k for k in valid if valid.get(k) != params.get(k))),
            )
            return valid
        return None

    async def _attempt(
        self, reg: _Registered, params: JSONObject, budget: CostBudget | None
    ) -> tuple[JSONObject, float]:
        spec = reg.spec
        reg.breaker.acquire()  # CircuitOpenError is transient: fallback/retry decide
        cost = max(0.0, reg.estimate(params))
        if budget is not None:
            try:
                budget.reserve(cost)
            except BudgetExceededError:
                reg.breaker.release_probe()
                raise
        verdict: bool | None = None
        try:
            if reg.bucket is not None:
                await reg.bucket.acquire(max_wait_s=spec.timeout_s)
            self.telemetry.emit(EventKind.TOOL_CALL, spec.name, cost=cost)
            try:
                raw = await asyncio.wait_for(reg.fn(dict(params)), spec.timeout_s)
            except TimeoutError as exc:
                raise ToolTimeoutError(f"{spec.name} exceeded {spec.timeout_s}s") from exc
            except ToolError:
                raise
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — unknown failure: classify as transient
                raise TransientToolError(f"{type(exc).__name__}: {exc}") from exc
            try:
                out = spec.output_schema.validate(raw)
            except SchemaError as exc:
                self.telemetry.emit(
                    EventKind.SCHEMA_REJECTED, spec.name, where="output", error=str(exc)
                )
                raise ToolOutputDriftError(str(exc)) from exc
            verdict = True
            return out, cost
        except TimeoutError as exc:  # bucket wait exceeded the tool timeout
            verdict = False
            raise ToolTimeoutError(str(exc)) from exc
        except ToolError as err:
            # Our own budget refusal is not the tool's fault; don't trip its breaker.
            verdict = None if isinstance(err, BudgetExceededError) else False
            raise
        finally:
            if verdict is True:
                reg.breaker.record_success()
                if budget is not None:
                    budget.commit(cost)
            else:
                if verdict is False:
                    reg.breaker.record_failure()
                else:
                    reg.breaker.release_probe()
                if budget is not None:
                    budget.refund(cost)

    # ---- capability routing with fallback ------------------------------------------------

    def candidates(self, capability: str, budget: CostBudget | None = None) -> list[str]:
        """Cheapest-first, healthy-first tools that can serve ``capability``."""
        regs = [r for r in self._tools.values() if capability in r.spec.capabilities]
        ranked = sorted(
            regs,
            key=lambda r: (
                r.breaker.state is BreakerState.OPEN,
                r.spec.cost_per_call,
                r.spec.name,
            ),
        )
        if budget is not None:
            ranked = [r for r in ranked if r.spec.cost_per_call <= budget.remaining + 1e-12]
        return [r.spec.name for r in ranked]

    async def route(
        self,
        capability: str,
        params: Mapping[str, object],
        *,
        budget: CostBudget | None = None,
        adapt: Callable[[str, Mapping[str, object]], Mapping[str, object]] | None = None,
    ) -> ToolOutcome:
        names = self.candidates(capability, budget)
        if not names:
            raise NoRouteError(f"no tool for capability {capability!r} within budget")
        tried: list[str] = []
        errors: list[str] = []
        for name in names:
            p = adapt(name, params) if adapt else params
            outcome = await self.invoke(name, p, budget=budget)
            if outcome.ok:
                return ToolOutcome(
                    outcome.tool,
                    True,
                    outcome.output,
                    outcome.attempts,
                    outcome.cost,
                    outcome.params,
                    fallbacks=tuple(tried),
                )
            tried.append(name)
            errors.append(f"{name}: {outcome.error}")
            self.telemetry.emit(EventKind.TOOL_FALLBACK, name, capability=capability, error=outcome.error)
        return ToolOutcome(
            names[-1], False, {}, 0, 0.0, {}, error=" | ".join(errors), fallbacks=tuple(tried)
        )

    # ---- transactions --------------------------------------------------------------------

    def transaction(self, *, budget: CostBudget | None = None) -> Transaction:
        return Transaction(self, budget)

    def health(self) -> dict[str, str]:
        return {n: r.breaker.state.value for n, r in sorted(self._tools.items())}


class Transaction:
    """Saga: every successful step with a compensation is recorded; on failure (a failed
    outcome or any exception in the block) compensations run in reverse order."""

    def __init__(self, runtime: ToolRuntime, budget: CostBudget | None) -> None:
        self._rt = runtime
        self._budget = budget
        self._applied: list[_Applied] = []
        self.rolled_back = False
        self.rollback_errors: tuple[str, ...] = ()

    async def invoke(self, name: str, params: Mapping[str, object]) -> ToolOutcome:
        outcome = await self._rt.invoke(name, params, budget=self._budget)
        if not outcome.ok:
            raise PermanentToolError(f"step {name} failed: {outcome.error}")
        comp = self._rt._get(name).compensate
        if comp is not None:
            self._applied.append(_Applied(name, outcome.params, outcome.output, comp))
        return outcome

    async def rollback(self) -> None:
        failures: list[str] = []
        for step in reversed(self._applied):
            try:
                await step.compensate(step.params, step.output)
            except Exception as exc:  # noqa: BLE001 — keep compensating the rest
                failures.append(f"{step.tool}: {exc}")
        self._applied.clear()
        self.rolled_back = True
        self.rollback_errors = tuple(failures)
        self._rt.telemetry.emit(EventKind.ROLLBACK, "tx", failures=len(failures))
        if failures:
            raise RollbackError(failures)

    async def __aenter__(self) -> Transaction:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc is not None:
            await self.rollback()  # RollbackError, if any, chains onto the original error
        else:
            self._applied.clear()


# ---- subprocess isolation ----------------------------------------------------------------

_RUNNER = (
    "import sys,json,importlib\n"
    "sys.path[:0]=json.loads(sys.argv[1])\n"
    "m,f=sys.argv[2].split(':',1)\n"
    "fn=getattr(importlib.import_module(m),f)\n"
    "out=fn(json.loads(sys.stdin.read()))\n"
    "sys.stdout.write(json.dumps(out,allow_nan=False))\n"
)


def _limits(mem_mb: int, cpu_s: int) -> Callable[[], None]:
    def apply() -> None:
        try:
            import resource

            mem = mem_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        except (ImportError, ValueError, OSError):
            pass  # non-POSIX or limit not permitted: timeout + kill still apply

    return apply


def subprocess_tool(
    target: str,
    *,
    search_path: Sequence[str] = (),
    mem_mb: int = 512,
    cpu_s: int = 30,
    env_allow: Sequence[str] = ("PATH", "LANG", "LC_ALL"),
) -> ToolFn:
    """Wrap ``"package.module:function"`` (a sync ``dict -> dict`` function) as an isolated
    ``ToolFn``. Each call is a fresh ``python -I`` process with a scrubbed environment and
    rlimits; on cancellation/timeout the process is killed, never orphaned."""

    if ":" not in target:
        raise ValueError("target must look like 'module:function'")
    env = {k: os.environ[k] for k in env_allow if k in os.environ}

    async def run(params: JSONObject) -> JSONObject:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-c",
            _RUNNER,
            json.dumps(list(search_path)),
            target,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            preexec_fn=_limits(mem_mb, cpu_s) if os.name == "posix" else None,
        )
        try:
            out, err = await proc.communicate(json.dumps(params).encode())
        except asyncio.CancelledError:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise
        if proc.returncode != 0:
            tail = err.decode(errors="replace").strip().splitlines()[-1:] or ["no stderr"]
            raise TransientToolError(f"{target} exited {proc.returncode}: {tail[0][:300]}")
        try:
            decoded = json.loads(out.decode())
        except ValueError as exc:
            raise ToolOutputDriftError(f"{target} wrote non-JSON output") from exc
        if not isinstance(decoded, dict):
            raise ToolOutputDriftError(f"{target} returned {type(decoded).__name__}, not object")
        return decoded

    return run


__all__ = [
    "CircuitOpenError",
    "Compensation",
    "Isolation",
    "ParamMutator",
    "ToolFn",
    "ToolOutcome",
    "ToolRuntime",
    "ToolSpec",
    "Transaction",
    "subprocess_tool",
]
