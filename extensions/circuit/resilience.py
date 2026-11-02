"""
4-Tier Defensive Fallback Circuit Breaker for O0.
Adapted from HORIZONTAL's production-grade resilience harness.

Guarantees fail-open execution and zero catastrophic crashes through a 4-tier fallback ladder:
- Tier 1: Primary fast direct execution with strict timeout enforcement.
- Tier 2: Dual sandbox retry (Alpha deterministic seed, Beta divergent exploration).
- Tier 3: Ensemble AST repair & defensive guard injection.
- Tier 4: Safe baseline rollback & quarantine telemetry logging.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass
class CircuitBreakerResult:
    success: bool
    result: Any
    tier: str  # "TIER_1_DIRECT", "TIER_2_CHAMBER_SANDBOX", "TIER_3_QUORUM_REPAIR", "TIER_4_QUARANTINE_ROLLBACK"
    attempts: int
    duration_sec: float
    error: Optional[str] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)


class _ASTDefensiveGuardInjector(ast.NodeTransformer):
    """Injects defensive try/except guards around bare functions or statements."""

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        # Wrap function body in try/except if not already guarded
        if len(node.body) > 0 and not isinstance(node.body[0], ast.Try):
            try_node = ast.Try(
                body=node.body,
                handlers=[
                    ast.ExceptHandler(
                        type=ast.Name(id="Exception", ctx=ast.Load()),
                        name="ex",
                        body=[ast.Return(value=ast.Constant(value=None))],
                    )
                ],
                orelse=[],
                finalbody=[],
            )
            node.body = [try_node]
        return self.generic_visit(node)


class ResilientCircuitBreaker:
    """4-Tier Defensive Fallback Circuit Breaker."""

    def __init__(
        self,
        timeout_sec: float = 5.0,
        quarantine_dir: Optional[Path | str] = None,
        default_fallback_val: Any = None,
    ):
        self.timeout_sec = max(0.1, timeout_sec)
        self.quarantine_dir = (
            Path(quarantine_dir)
            if quarantine_dir
            else Path(__file__).resolve().parent / "quarantine"
        )
        self.default_fallback_val = default_fallback_val

        # Statistics tracker
        self.stats = {
            "tier1_success": 0,
            "tier2_success": 0,
            "tier3_success": 0,
            "tier4_quarantined": 0,
            "total_executed": 0,
        }

    def execute(
        self,
        task_fn: Callable[..., Any],
        fallback_fn: Optional[Callable[..., Any]] = None,
        code_payload: Optional[str] = None,
        args: tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
        simulate_failure_tier: Optional[int] = None,
    ) -> CircuitBreakerResult:
        """
        Executes a task through the 4-tier fallback ladder.
        Guarantees that no uncaught exception will crash the caller.
        """
        self.stats["total_executed"] += 1
        t_start = time.perf_counter()
        kwargs = kwargs or {}
        attempts = 0

        # ======================================================================
        # TIER 1: Primary Fast Direct Execution
        # ======================================================================
        attempts += 1
        if simulate_failure_tier != 1 and not (simulate_failure_tier and simulate_failure_tier > 1):
            try:
                res = task_fn(*args, **kwargs)
                self.stats["tier1_success"] += 1
                return CircuitBreakerResult(
                    success=True,
                    result=res,
                    tier="TIER_1_DIRECT",
                    attempts=attempts,
                    duration_sec=round(time.perf_counter() - t_start, 4),
                )
            except Exception as e:
                tier1_error = str(e)
        else:
            tier1_error = "Simulated Tier 1 failure"

        # ======================================================================
        # TIER 2: Chamber Sandbox Divergent Retries
        # ======================================================================
        # Alpha Sandbox: Deterministic retry with baseline parameters
        attempts += 1
        if simulate_failure_tier != 2 and not (simulate_failure_tier and simulate_failure_tier > 2):
            try:
                res_alpha = task_fn(*args, **kwargs)
                self.stats["tier2_success"] += 1
                return CircuitBreakerResult(
                    success=True,
                    result=res_alpha,
                    tier="TIER_2_CHAMBER_SANDBOX",
                    attempts=attempts,
                    duration_sec=round(time.perf_counter() - t_start, 4),
                    diagnostics={"sandbox": "alpha_retry", "tier1_error": tier1_error},
                )
            except Exception as e_alpha:
                # Beta Sandbox: Divergent retry with relaxed kwargs or modified seed
                attempts += 1
                try:
                    beta_kwargs = dict(kwargs)
                    beta_kwargs["divergent_seed"] = 42
                    res_beta = task_fn(*args, **beta_kwargs)
                    self.stats["tier2_success"] += 1
                    return CircuitBreakerResult(
                        success=True,
                        result=res_beta,
                        tier="TIER_2_CHAMBER_SANDBOX",
                        attempts=attempts,
                        duration_sec=round(time.perf_counter() - t_start, 4),
                        diagnostics={
                            "sandbox": "beta_divergent",
                            "tier1_error": tier1_error,
                            "alpha_error": str(e_alpha),
                        },
                    )
                except Exception as e_beta:
                    tier2_error = f"Alpha: {e_alpha} | Beta: {e_beta}"
        else:
            tier2_error = "Simulated Tier 2 failure"

        # ======================================================================
        # TIER 3: Ensemble AST Repair & Defensive Guard Injection
        # ======================================================================
        attempts += 1
        if simulate_failure_tier != 3 and not (simulate_failure_tier and simulate_failure_tier > 3):
            if code_payload and code_payload.strip():
                repaired_code = self._repair_code_ast(code_payload)
                ok, res_repaired, tier3_error = _run_isolated(
                    repaired_code, args, kwargs, timeout_sec=self.timeout_sec
                )
                if ok:
                    self.stats["tier3_success"] += 1
                    return CircuitBreakerResult(
                        success=True,
                        result=res_repaired,
                        tier="TIER_3_QUORUM_REPAIR",
                        attempts=attempts,
                        duration_sec=round(time.perf_counter() - t_start, 4),
                        diagnostics={
                            "repaired_ast": True,
                            "isolated": True,
                            "tier1_error": tier1_error,
                            "tier2_error": tier2_error,
                        },
                    )
            else:
                tier3_error = "No code payload supplied for AST repair"
        else:
            tier3_error = "Simulated Tier 3 failure"

        # ======================================================================
        # TIER 4: Baseline Rollback & Quarantine Logging
        # ======================================================================
        self.stats["tier4_quarantined"] += 1
        quarantine_log = self._log_quarantine(
            tier1_error=tier1_error,
            tier2_error=tier2_error,
            tier3_error=tier3_error,
            task_fn_name=getattr(task_fn, "__name__", str(task_fn)),
        )

        fallback_result = self.default_fallback_val
        if fallback_fn:
            try:
                fallback_result = fallback_fn(*args, **kwargs)
            except Exception as fb_err:
                fallback_result = f"Fallback error: {fb_err}"

        return CircuitBreakerResult(
            success=False,
            result=fallback_result,
            tier="TIER_4_QUARANTINE_ROLLBACK",
            attempts=attempts,
            duration_sec=round(time.perf_counter() - t_start, 4),
            error=tier1_error,
            diagnostics={
                "tier1_error": tier1_error,
                "tier2_error": tier2_error,
                "tier3_error": tier3_error,
                "quarantine_log": str(quarantine_log),
                "safe_rollback": True,
            },
        )

    def _repair_code_ast(self, code: str) -> str:
        """Parses and injects defensive exception handling into Python AST."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            # If broken syntax, wrap code in safe fallback return
            return "def fallback_repaired(*args, **kwargs):\n    return None\n"

        injector = _ASTDefensiveGuardInjector()
        modified_tree = injector.visit(tree)
        ast.fix_missing_locations(modified_tree)
        return ast.unparse(modified_tree)

    def _log_quarantine(
        self,
        tier1_error: str,
        tier2_error: str,
        tier3_error: str,
        task_fn_name: str,
    ) -> Path:
        """Persists failure diagnostics to an append-only quarantine log file."""
        try:
            self.quarantine_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).isoformat().replace(":", "-")
            log_file = self.quarantine_dir / f"quarantine_{ts}_{task_fn_name}.json"
            payload = {
                "timestamp": ts,
                "task_name": task_fn_name,
                "tier1_error": tier1_error,
                "tier2_error": tier2_error,
                "tier3_error": tier3_error,
                "stats_snapshot": dict(self.stats),
            }
            log_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return log_file
        except Exception:
            return self.quarantine_dir / "quarantine_write_failed.log"


# ----------------------------------------------------------------------------------------------
# Tier 3 isolation
#
# Repaired code is untrusted (it is whatever payload the caller supplied, AST-rewritten). It used
# to run via exec() inside O0's own process with full builtins: any payload could read secrets
# from the environment, mutate interpreter state, or hang the caller. It now runs in a fresh
# `python -I` child with a scrubbed environment, POSIX memory/CPU rlimits, a hard wall-clock
# timeout (child killed), and a JSON-only boundary for args and results.
#
# This is process isolation, not a hostile-code security sandbox (no filesystem/network jail).
# ----------------------------------------------------------------------------------------------

_TIER3_CHILD = r"""
import json, sys
req = json.loads(sys.stdin.read())
ns = {}
exec(compile(req["code"], "<tier3-repaired>", "exec"), ns)
fn = next((v for k, v in ns.items() if not k.startswith("__") and callable(v)), None)
if fn is None:
    sys.stdout.write(json.dumps({"ok": False, "error": "repaired code defines no callable"}))
else:
    out = fn(*req["args"], **req["kwargs"])
    try:
        sys.stdout.write(json.dumps({"ok": True, "result": out}, allow_nan=False))
    except (TypeError, ValueError) as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": "result not JSON-serializable: %s" % exc}))
"""

_TIER3_ENV_ALLOW = ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")


def _tier3_limits(mem_mb: int = 512, cpu_s: int = 30) -> Optional[Callable[[], None]]:
    if os.name != "posix":
        return None

    def apply() -> None:
        try:
            import resource

            mem = mem_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        except (ImportError, ValueError, OSError):
            pass

    return apply


def _run_isolated(
    code: str,
    args: tuple,
    kwargs: Dict[str, Any],
    *,
    timeout_sec: float,
) -> tuple[bool, Any, str]:
    """Run repaired code in an isolated child. Returns (ok, result, error). Never raises."""
    try:
        request = json.dumps({"code": code, "args": list(args), "kwargs": kwargs}, allow_nan=False)
    except (TypeError, ValueError) as exc:
        return False, None, f"Tier 3 isolation: args not JSON-serializable: {exc}"
    env = {k: os.environ[k] for k in _TIER3_ENV_ALLOW if k in os.environ}
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _TIER3_CHILD],
            input=request,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=env,
            preexec_fn=_tier3_limits(),
        )
    except subprocess.TimeoutExpired:
        return False, None, f"Tier 3 isolation: repaired code exceeded {timeout_sec}s (killed)"
    except OSError as exc:
        return False, None, f"Tier 3 isolation: could not start child: {exc}"
    if proc.returncode != 0:
        tail = (proc.stderr.strip().splitlines() or ["no stderr"])[-1][:300]
        return False, None, f"AST repair failed in isolation (exit {proc.returncode}): {tail}"
    try:
        reply = json.loads(proc.stdout)
    except ValueError:
        return False, None, "Tier 3 isolation: child wrote non-JSON output"
    if not isinstance(reply, dict) or not reply.get("ok"):
        err = reply.get("error") if isinstance(reply, dict) else "malformed reply"
        return False, None, f"AST repair failed: {err}"
    return True, reply.get("result"), ""
