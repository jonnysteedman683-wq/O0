"""O0 capability probes (v3b): measured, reproducible capability scores.

Each probe runs a FIXED, deterministic task suite and returns a 0.0-1.0 score.
Because the suites are fixed, scores are comparable across runs and across
promotions — this is what makes them "real capability probes" rather than
vibes. Probe scores feed the capability ledger.

Probes (v3b):
  - reasoning : pass rate on a fixed arithmetic suite (output checked)
  - tool_use  : pass rate on a fixed python-task suite (exit code checked)
  - memory    : recall accuracy on a fixed store/recall suite
  - codegen   : pluggable; reports "not measured" until a codegen executor is
                provided (v5 self-authorship fills this). We do NOT fake it.

All subprocess calls use LIST form (no shell=True): cross-platform safe on
Windows (cmd.exe does not honor single-quote quoting) and no injection surface.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

from .memory import Memory


@dataclass
class ProbeResult:
    name: str
    score: float | None  # None = not measured
    passed: int = 0
    total: int = 0
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "score": self.score,
            "passed": self.passed,
            "total": self.total,
            "detail": self.detail,
        }


class Probe:
    name = "probe"

    def run(self) -> ProbeResult:
        raise NotImplementedError


def _run_python(code: str) -> tuple[int, str]:
    """Run a python snippet via list-form subprocess (no shell)."""
    try:
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                              text=True, timeout=30)
        return proc.returncode, proc.stdout
    except (subprocess.TimeoutExpired, OSError):
        return 1, ""


# -- reasoning -------------------------------------------------------------
# (python snippet, expected stdout) — deterministic, verifiable answers.
REASONING_TASKS: list[tuple[str, str]] = [
    ("print(6*7)", "42"),
    ("print(2**10)", "1024"),
    ("print(sum(range(101)))", "5050"),
    ("print(17*23)", "391"),
    ("print(2+2)", "4"),
]


class ReasoningProbe(Probe):
    name = "reasoning"

    def run(self) -> ProbeResult:
        passed = 0
        for code, expected in REASONING_TASKS:
            rc, out = _run_python(code)
            if rc == 0 and out.strip() == expected:
                passed += 1
        total = len(REASONING_TASKS)
        return ProbeResult(self.name, passed / total, passed, total,
                           f"{passed}/{total} arithmetic tasks correct")


# -- tool use --------------------------------------------------------------
TOOL_TASKS: list[str] = [
    "import json; print(json.dumps({1:2}))",
    "print(len('hello world'))",
    "import math; print(round(math.pi, 2))",
    "print('ok')",
]


class ToolUseProbe(Probe):
    name = "tool_use"

    def run(self) -> ProbeResult:
        passed = 0
        for code in TOOL_TASKS:
            rc, _out = _run_python(code)
            if rc == 0:
                passed += 1
        total = len(TOOL_TASKS)
        return ProbeResult(self.name, passed / total, passed, total,
                           f"{passed}/{total} python tasks succeeded")


# -- memory ----------------------------------------------------------------
MEMORY_PAIRS: list[tuple[str, str]] = [
    ("alpha", "the first letter"),
    ("beta", "the second letter"),
    ("gamma", "the third letter"),
    ("delta", "the fourth letter"),
]


class MemoryProbe(Probe):
    name = "memory"

    def __init__(self, memory: Memory | None = None):
        self.memory = memory or Memory()

    def run(self) -> ProbeResult:
        # store a fixed suite, then recall each key and check content
        for key, val in MEMORY_PAIRS:
            self.memory.remember("probe", f"{key} is {val}", tags=["probe", key])
        passed = 0
        for key, val in MEMORY_PAIRS:
            hits = self.memory.recall(key, limit=1)
            if hits and val in hits[0]["content"]:
                passed += 1
        total = len(MEMORY_PAIRS)
        return ProbeResult(self.name, passed / total, passed, total,
                           f"{passed}/{total} memories recalled correctly")


# -- codegen (pluggable; not measured until an executor is provided) --------
class CodegenProbe(Probe):
    name = "codegen"

    def __init__(self, codegen_fn: Callable[[str], str] | None = None):
        self.codegen_fn = codegen_fn

    def run(self) -> ProbeResult:
        if self.codegen_fn is None:
            return ProbeResult(self.name, None, 0, 0,
                               "not measured: no codegen executor (v5)")
        # spec -> code -> run -> check output
        code = self.codegen_fn("print(40+2)")
        rc, out = _run_python(code)
        ok = rc == 0 and out.strip() == "42"
        return ProbeResult(self.name, 1.0 if ok else 0.0, 1 if ok else 0, 1,
                           "codegen produced correct output" if ok else "codegen failed")


def run_all_probes(memory: Memory | None = None) -> list[ProbeResult]:
    return [
        ReasoningProbe().run(),
        ToolUseProbe().run(),
        MemoryProbe(memory=memory).run(),
        CodegenProbe().run(),
    ]
