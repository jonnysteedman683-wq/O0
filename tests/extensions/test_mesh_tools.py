"""Tool runtime: validation, retry + parameter mutation, rate-limit cascade prevention,
breakers, cost-aware fallback routing, saga rollback, and subprocess isolation."""

from __future__ import annotations

import asyncio
import sys
import textwrap
from pathlib import Path

import pytest

from extensions.mesh import (
    BreakerState,
    CostBudget,
    EventKind,
    Field,
    Kind,
    NoRouteError,
    PermanentToolError,
    RateLimitedError,
    RetryPolicy,
    RollbackError,
    Schema,
    Telemetry,
    TokenBucket,
    ToolRuntime,
    ToolSpec,
    TransientToolError,
    subprocess_tool,
)
from extensions.mesh.errors import ToolError
from extensions.mesh.jsontypes import JSONObject

IN = Schema("q", 1, (Field("q", Kind.STR), Field("k", Kind.INT, required=False)))
OUT = Schema("r", 1, (Field("r", Kind.STR),))
FAST = RetryPolicy(max_attempts=4, base_delay_s=0.001, max_delay_s=0.005)


def run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(asyncio.wait_for(coro, 20))


def spec(name: str, cost: float = 0.0, **kw: object) -> ToolSpec:
    return ToolSpec(name, IN, OUT, frozenset({"answer"}), cost_per_call=cost, **kw)  # type: ignore[arg-type]


def test_input_schema_rejection_never_calls_tool() -> None:
    calls: list[JSONObject] = []

    async def fn(p: JSONObject) -> JSONObject:
        calls.append(p)
        return {"r": "x"}

    async def go() -> None:
        rt = ToolRuntime(retry=FAST)
        rt.register(spec("t"), fn)
        out = await rt.invoke("t", {"q": 1})
        assert not out.ok and out.error and "input" in out.error and calls == []

    run(go())


def test_transient_failures_retry_with_parameter_mutation() -> None:
    seen: list[int] = []

    async def fn(p: JSONObject) -> JSONObject:
        k = p.get("k", 8)
        assert isinstance(k, int)
        seen.append(k)
        if k > 2:
            raise TransientToolError("context too long")
        return {"r": f"ok@{k}"}

    def halve(p: JSONObject, err: ToolError, attempt: int) -> JSONObject | None:
        k = p.get("k", 8)
        return {**p, "k": k // 2} if isinstance(k, int) and k > 1 else None

    async def go() -> None:
        tel = Telemetry()
        rt = ToolRuntime(telemetry=tel, retry=FAST, breaker_threshold=10)
        rt.register(spec("t"), fn, mutators=[halve])
        out = await rt.invoke("t", {"q": "x", "k": 8})
        assert out.ok and out.output == {"r": "ok@2"} and out.attempts == 3
        assert out.params["k"] == 2
        assert tel.snapshot()["tool.mutated"] == 2

    run(go())
    assert seen == [8, 4, 2]


def test_mutator_cannot_smuggle_invalid_params() -> None:
    async def fn(p: JSONObject) -> JSONObject:
        raise TransientToolError("nope")

    def evil(p: JSONObject, err: ToolError, attempt: int) -> JSONObject | None:
        return {**p, "k": "not-an-int"}

    async def go() -> None:
        tel = Telemetry()
        rt = ToolRuntime(telemetry=tel, retry=FAST, breaker_threshold=10)
        rt.register(spec("t"), fn, mutators=[evil])
        out = await rt.invoke("t", {"q": "x", "k": 1})
        assert not out.ok and out.params == {"q": "x", "k": 1}
        assert "tool.mutated" not in tel.snapshot()

    run(go())


def test_permanent_error_and_non_idempotent_tools_are_not_retried() -> None:
    n = {"perm": 0, "mut": 0}

    async def perm(p: JSONObject) -> JSONObject:
        n["perm"] += 1
        raise PermanentToolError("bad request")

    async def mut(p: JSONObject) -> JSONObject:
        n["mut"] += 1
        raise TransientToolError("maybe applied")

    async def go() -> None:
        rt = ToolRuntime(retry=FAST)
        rt.register(spec("perm"), perm)
        rt.register(spec("mut", idempotent=False), mut)
        assert not (await rt.invoke("perm", {"q": "x"})).ok
        assert not (await rt.invoke("mut", {"q": "x"})).ok

    run(go())
    assert n == {"perm": 1, "mut": 1}


def test_output_drift_is_caught_and_routes_to_fallback() -> None:
    async def drifted(p: JSONObject) -> JSONObject:
        return {"result": "renamed field"}  # upstream changed its response shape

    async def stable(p: JSONObject) -> JSONObject:
        return {"r": "stable"}

    async def go() -> None:
        tel = Telemetry()
        rt = ToolRuntime(telemetry=tel, retry=FAST)
        rt.register(spec("cheap", cost=0.1), drifted)
        rt.register(spec("pricey", cost=1.0), stable)
        out = await rt.route("answer", {"q": "x"})
        assert out.ok and out.tool == "pricey" and out.fallbacks == ("cheap",)
        assert tel.snapshot()["schema.rejected"] == 1

    run(go())


def test_rate_limit_penalizes_shared_bucket_preventing_cascade() -> None:
    upstream_calls: list[float] = []
    loop_time = {"limited": False}

    async def fn(p: JSONObject) -> JSONObject:
        upstream_calls.append(asyncio.get_running_loop().time())
        if not loop_time["limited"]:
            loop_time["limited"] = True
            raise RateLimitedError(retry_after_s=0.1)
        return {"r": "ok"}

    async def go() -> None:
        tel = Telemetry()
        rt = ToolRuntime(telemetry=tel, retry=FAST, breaker_threshold=50)
        rt.register(spec("t", rate_per_s=1000, burst=1), fn)
        outs = await asyncio.gather(*(rt.invoke("t", {"q": str(i)}) for i in range(10)))
        assert all(o.ok for o in outs)
        assert tel.snapshot()["tool.rate_limited"] == 1  # one 429, not ten
        t0 = upstream_calls[0]
        assert all(t - t0 >= 0.09 for t in upstream_calls[1:])  # everyone honoured the penalty

    run(go())


def test_token_bucket_rate_and_penalty() -> None:
    async def go() -> None:
        b = TokenBucket(rate_per_s=100, burst=2)
        assert await b.acquire() == 0 and await b.acquire() == 0
        assert await b.acquire() > 0
        b.penalize(0.05)
        assert b.wait_time() >= 0.04
        with pytest.raises(TimeoutError):
            await b.acquire(max_wait_s=0.001)

    run(go())


def test_breaker_opens_then_half_open_probe_closes_it() -> None:
    now = {"t": 0.0}
    healthy = {"v": False}

    async def fn(p: JSONObject) -> JSONObject:
        if not healthy["v"]:
            raise TransientToolError("down")
        return {"r": "up"}

    async def go() -> None:
        rt = ToolRuntime(retry=RetryPolicy(max_attempts=1), breaker_threshold=2, breaker_recovery_s=5)
        rt.register(spec("t"), fn)
        rt.breaker("t")._clock = lambda: now["t"]
        for _ in range(2):
            await rt.invoke("t", {"q": "x"})
        assert rt.breaker("t").state is BreakerState.OPEN
        out = await rt.invoke("t", {"q": "x"})
        assert not out.ok and out.error and "CircuitOpenError" in out.error
        now["t"] = 6.0
        healthy["v"] = True
        assert rt.breaker("t").state is BreakerState.HALF_OPEN
        assert (await rt.invoke("t", {"q": "x"})).ok
        assert rt.breaker("t").state is BreakerState.CLOSED

    run(go())


def test_cost_aware_routing_respects_budget() -> None:
    async def fn(p: JSONObject) -> JSONObject:
        return {"r": "x"}

    async def go() -> None:
        rt = ToolRuntime(retry=FAST)
        rt.register(spec("cheap", cost=1.0), fn)
        rt.register(spec("gold", cost=5.0), fn)
        budget = CostBudget(3.0)
        assert rt.candidates("answer", budget) == ["cheap"]
        out = await rt.route("answer", {"q": "x"}, budget=budget)
        assert out.tool == "cheap" and budget.spent == 1.0
        assert rt.candidates("answer", CostBudget(0.5)) == []
        with pytest.raises(NoRouteError):
            await rt.route("answer", {"q": "x"}, budget=CostBudget(0.5))

    run(go())


def test_concurrent_calls_cannot_jointly_overspend() -> None:
    async def fn(p: JSONObject) -> JSONObject:
        await asyncio.sleep(0.01)
        return {"r": "x"}

    async def go() -> None:
        rt = ToolRuntime(retry=RetryPolicy(max_attempts=1))
        rt.register(spec("t", cost=1.0), fn)
        budget = CostBudget(3.0)
        outs = await asyncio.gather(*(rt.invoke("t", {"q": "x"}, budget=budget) for _ in range(6)))
        assert sum(o.ok for o in outs) == 3 and budget.spent == 3.0 and budget.reserved == 0

    run(go())


def test_timeout_is_transient_and_retried() -> None:
    n = {"c": 0}

    async def fn(p: JSONObject) -> JSONObject:
        n["c"] += 1
        if n["c"] == 1:
            await asyncio.sleep(1)
        return {"r": "late-but-ok"}

    async def go() -> None:
        rt = ToolRuntime(retry=FAST)
        rt.register(spec("t", timeout_s=0.02), fn)
        out = await rt.invoke("t", {"q": "x"})
        assert out.ok and out.attempts == 2

    run(go())


def test_transaction_rolls_back_in_reverse_order() -> None:
    log: list[str] = []

    def step(name: str, fail: bool = False):  # type: ignore[no-untyped-def]
        async def fn(p: JSONObject) -> JSONObject:
            if fail:
                raise PermanentToolError("step failed")
            log.append(f"do:{name}")
            return {"r": name}

        async def undo(p: JSONObject, out: JSONObject) -> None:
            log.append(f"undo:{out['r']}")

        return fn, undo

    async def go() -> None:
        tel = Telemetry()
        rt = ToolRuntime(telemetry=tel, retry=FAST)
        for name, fail in (("a", False), ("b", False), ("c", True)):
            fn, undo = step(name, fail)
            rt.register(spec(name), fn, compensate=undo)
        with pytest.raises(PermanentToolError):
            async with rt.transaction() as tx:
                await tx.invoke("a", {"q": "1"})
                await tx.invoke("b", {"q": "2"})
                await tx.invoke("c", {"q": "3"})
        assert tel.snapshot()["tx.rollback"] == 1

    run(go())
    assert log == ["do:a", "do:b", "undo:b", "undo:a"]


def test_rollback_continues_past_failing_compensation() -> None:
    undone: list[str] = []

    async def ok(p: JSONObject) -> JSONObject:
        return {"r": str(p["q"])}

    async def undo_ok(p: JSONObject, out: JSONObject) -> None:
        undone.append(str(out["r"]))

    async def undo_bad(p: JSONObject, out: JSONObject) -> None:
        raise OSError("cannot undo")

    async def go() -> None:
        rt = ToolRuntime(retry=FAST)
        rt.register(spec("a"), ok, compensate=undo_ok)
        rt.register(spec("b"), ok, compensate=undo_bad)
        tx = rt.transaction()
        await tx.invoke("a", {"q": "first"})
        await tx.invoke("b", {"q": "second"})
        with pytest.raises(RollbackError) as ei:
            await tx.rollback()
        assert ei.value.failures and undone == ["first"] and tx.rolled_back

    run(go())


@pytest.fixture()
def tool_module(tmp_path: Path) -> Path:
    (tmp_path / "isolated_tools.py").write_text(
        textwrap.dedent(
            """
            import os, time
            def answer(p):
                return {"r": p["q"].upper() + ("|secret" if os.environ.get("SECRET_TOKEN") else "")}
            def hang(p):
                time.sleep(30)
                return {"r": "never"}
            def crash(p):
                raise SystemExit(3)
            """
        )
    )
    return tmp_path


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process isolation")
def test_subprocess_tool_isolates_env_and_kills_on_timeout(
    tool_module: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SECRET_TOKEN", "do-not-leak")
    path = [str(tool_module)]

    async def go() -> None:
        rt = ToolRuntime(retry=RetryPolicy(max_attempts=1))
        rt.register(spec("ok"), subprocess_tool("isolated_tools:answer", search_path=path))
        rt.register(spec("hang", timeout_s=0.5), subprocess_tool("isolated_tools:hang", search_path=path))
        rt.register(spec("crash"), subprocess_tool("isolated_tools:crash", search_path=path))
        ok = await rt.invoke("ok", {"q": "hi"})
        assert ok.ok and ok.output == {"r": "HI"}  # secret env var did not cross the boundary
        hang = await rt.invoke("hang", {"q": "x"})
        assert not hang.ok and hang.error and "ToolTimeoutError" in hang.error
        crash = await rt.invoke("crash", {"q": "x"})
        assert not crash.ok and crash.error and "exited 3" in crash.error

    run(go())


def test_retry_schedule_is_deterministic_and_bounded() -> None:
    p = RetryPolicy(max_attempts=6, base_delay_s=0.1, max_delay_s=0.5, seed=42)
    assert p.delays() == p.delays()
    assert len(p.delays()) == 5 and max(p.delays()) <= 0.5


def test_telemetry_records_tool_failure() -> None:
    async def fn(p: JSONObject) -> JSONObject:
        raise TransientToolError("x")

    async def go() -> None:
        tel = Telemetry()
        rt = ToolRuntime(telemetry=tel, retry=FAST, breaker_threshold=99)
        rt.register(spec("t"), fn)
        await rt.invoke("t", {"q": "x"})
        assert tel.memory().of(EventKind.TOOL_FAILED)  # type: ignore[union-attr]

    run(go())
