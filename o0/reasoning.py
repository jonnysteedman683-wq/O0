"""O0 reasoning loop (v2): plan -> execute -> verify -> reflect -> (retry|accept).

The missing step that makes this a LOOP rather than a pipeline is REFLECT:
after verification, O0 analyzes the result, extracts a lesson, stores it to
episodic memory, and decides whether to retry (bounded) or accept. A failed
task is not discarded — it becomes a lesson and a bounded retry.

Executor is pluggable so v2 can run shell/python tasks and v3+ can run real
capability probes through the same loop.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Callable

from .memory import Memory


@dataclass
class Verdict:
    passed: bool
    detail: str = ""


@dataclass
class StepResult:
    step: str
    output: str
    verdict: Verdict
    attempts: int = 1


class ShellExecutor:
    """Executes a task as a shell command. Returns (exit_code, stdout)."""

    def execute(self, task: str) -> tuple[int, str]:
        proc = subprocess.run(
            task, shell=True, capture_output=True, text=True, timeout=120
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


class ReasoningLoop:
    """The full agentic cycle with the reflect step closing the loop."""

    def __init__(self, memory: Memory | None = None, max_retries: int = 2,
                 executor: object | None = None):
        self.memory = memory or Memory()
        self.max_retries = max_retries
        self.executor = executor or ShellExecutor()

    # -- the four steps -----------------------------------------------------
    def plan(self, task: str) -> list[str]:
        """Decompose a task into ordered steps (v2: single-step shell task)."""
        return [task]

    def execute(self, step: str) -> tuple[int, str]:
        return self.executor.execute(step)

    def verify(self, task: str, step: str, exit_code: int, output: str) -> Verdict:
        """Acceptance: exit code 0 and non-empty output (v2 default)."""
        if exit_code != 0:
            return Verdict(False, f"exit_code={exit_code}")
        if not output.strip():
            return Verdict(False, "empty output")
        return Verdict(True, "exit 0, output present")

    def reflect(self, task: str, step: str, exit_code: int, output: str,
                verdict: Verdict) -> str:
        """Extract a lesson from the outcome and store it to memory."""
        if verdict.passed:
            lesson = f"task succeeded: {task[:80]}"
            kind = "success"
        else:
            lesson = f"task failed ({verdict.detail}): {task[:80]}"
            kind = "failure"
        self.memory.remember(kind, lesson, tags=["reasoning", kind])
        return lesson

    # -- the loop -----------------------------------------------------------
    def run(self, task: str) -> dict:
        steps = self.plan(task)
        results: list[StepResult] = []
        for step in steps:
            attempts = 0
            last: StepResult | None = None
            while attempts <= self.max_retries:
                attempts += 1
                exit_code, output = self.execute(step)
                verdict = self.verify(task, step, exit_code, output)
                lesson = self.reflect(task, step, exit_code, output, verdict)
                last = StepResult(step=step, output=output[:200],
                                  verdict=verdict, attempts=attempts)
                if verdict.passed:
                    break
                # reflect step decides: bounded retry, then accept failure
            results.append(last)
        all_passed = all(r.verdict.passed for r in results)
        return {
            "task": task,
            "passed": all_passed,
            "steps": [
                {
                    "step": r.step,
                    "verdict": r.verdict.passed,
                    "detail": r.verdict.detail,
                    "attempts": r.attempts,
                    "output": r.output,
                }
                for r in results
            ],
        }
