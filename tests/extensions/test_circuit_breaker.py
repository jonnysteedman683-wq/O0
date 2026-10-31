"""Unit tests for the 4-Tier Defensive Fallback Circuit Breaker."""

from pathlib import Path

from extensions.circuit.resilience import (
    CircuitBreakerResult,
    ResilientCircuitBreaker,
)


def test_tier_1_direct_success():
    cb = ResilientCircuitBreaker()

    def healthy_task(x: int, y: int) -> int:
        return x + y

    res = cb.execute(healthy_task, args=(10, 25))
    assert res.success is True
    assert res.result == 35
    assert res.tier == "TIER_1_DIRECT"
    assert res.attempts == 1
    assert cb.stats["tier1_success"] == 1


def test_tier_2_chamber_sandbox_retry():
    cb = ResilientCircuitBreaker()
    call_count = 0

    def flaky_task(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Fails on attempt 1 (Tier 1), succeeds on attempt 2 (Tier 2 Alpha sandbox)
        if call_count == 1:
            raise RuntimeError("Transient connection timeout")
        return "recovered_value"

    res = cb.execute(flaky_task)
    assert res.success is True
    assert res.result == "recovered_value"
    assert res.tier == "TIER_2_CHAMBER_SANDBOX"
    assert res.attempts == 2
    assert cb.stats["tier2_success"] == 1


def test_tier_3_ast_repair_on_code_payload():
    cb = ResilientCircuitBreaker()

    # Code that throws an unhandled ZeroDivisionError
    flawed_code = """
def compute(val):
    # This throws ZeroDivisionError if not guarded
    x = 10 / 0
    return val * 2
"""

    def failing_task(*args, **kwargs):
        raise ZeroDivisionError("division by zero")

    res = cb.execute(
        task_fn=failing_task,
        code_payload=flawed_code,
        args=(5,),
        simulate_failure_tier=2,  # Force past Tier 2 to Tier 3
    )

    assert res.success is True
    assert res.tier == "TIER_3_QUORUM_REPAIR"
    # AST defensive wrapper caught exception and returned safe None
    assert res.result is None
    assert cb.stats["tier3_success"] == 1


def test_tier_4_quarantine_rollback_fail_open(tmp_path: Path):
    quarantine_dir = tmp_path / "quarantine"
    cb = ResilientCircuitBreaker(
        quarantine_dir=quarantine_dir,
        default_fallback_val="safe_default",
    )

    def catastrophic_task():
        raise ValueError("Unrecoverable corruption")

    def safe_fallback():
        return "fallback_recovered"

    res = cb.execute(
        task_fn=catastrophic_task,
        fallback_fn=safe_fallback,
        simulate_failure_tier=3,  # Force all the way to Tier 4
    )

    # Fail-open invariant: Does not raise or crash
    assert res.success is False
    assert res.result == "fallback_recovered"
    assert res.tier == "TIER_4_QUARANTINE_ROLLBACK"
    assert res.error is not None
    assert cb.stats["tier4_quarantined"] == 1

    # Verify quarantine log was written
    logs = list(quarantine_dir.glob("quarantine_*.json"))
    assert len(logs) == 1
    content = logs[0].read_text(encoding="utf-8")
    assert "catastrophic_task" in content


# --- Tier 3 isolation ---------------------------------------------------------------------------

import os  # noqa: E402
import sys  # noqa: E402

import pytest  # noqa: E402


def _force_tier3(cb: ResilientCircuitBreaker, code: str, *args, **kwargs):
    def failing_task(*a, **k):
        raise RuntimeError("primary failed")

    return cb.execute(failing_task, code_payload=code, args=args, kwargs=kwargs,
                      simulate_failure_tier=2)


def test_tier_3_returns_real_result_from_isolated_child(tmp_path: Path):
    cb = ResilientCircuitBreaker(quarantine_dir=tmp_path)
    res = _force_tier3(cb, "def double(v):\n    return {'v': v * 2}\n", 21)
    assert res.success and res.tier == "TIER_3_QUORUM_REPAIR"
    assert res.result == {"v": 42}
    assert res.diagnostics["isolated"] is True


def test_tier_3_cannot_read_parent_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("O0_TEST_SECRET", "do-not-leak")
    cb = ResilientCircuitBreaker(quarantine_dir=tmp_path)
    res = _force_tier3(cb, "def peek():\n    import os\n    return os.environ.get('O0_TEST_SECRET', 'absent')\n")
    assert res.success and res.result == "absent"


def test_tier_3_cannot_mutate_parent_process(tmp_path: Path):
    cb = ResilientCircuitBreaker(quarantine_dir=tmp_path)
    code = "import os, sys\ndef poison():\n    os.environ['O0_POISONED'] = '1'\n    sys.modules.clear()\n    return 'done'\n"
    res = _force_tier3(cb, code)
    assert res.success and res.result == "done"
    assert "O0_POISONED" not in os.environ and "json" in sys.modules


def test_tier_3_hang_is_killed_and_falls_open_to_tier_4(tmp_path: Path):
    cb = ResilientCircuitBreaker(timeout_sec=0.5, quarantine_dir=tmp_path, default_fallback_val="safe")
    res = _force_tier3(cb, "def spin():\n    while True:\n        pass\n")
    assert not res.success and res.tier == "TIER_4_QUARANTINE_ROLLBACK"
    assert res.result == "safe"
    assert "exceeded" in res.diagnostics["tier3_error"]


def test_tier_3_without_callable_no_longer_crashes_tier_4(tmp_path: Path):
    # Regression: tier3_error used to be unbound here, raising NameError out of execute().
    cb = ResilientCircuitBreaker(quarantine_dir=tmp_path, default_fallback_val="safe")
    res = _force_tier3(cb, "x = 1\n")
    assert res.tier == "TIER_4_QUARANTINE_ROLLBACK" and res.result == "safe"
    assert "no callable" in res.diagnostics["tier3_error"]


def test_tier_3_non_json_args_fall_open(tmp_path: Path):
    cb = ResilientCircuitBreaker(quarantine_dir=tmp_path, default_fallback_val="safe")
    res = _force_tier3(cb, "def f(x):\n    return 1\n", object())
    assert res.tier == "TIER_4_QUARANTINE_ROLLBACK"
    assert "JSON-serializable" in res.diagnostics["tier3_error"]
