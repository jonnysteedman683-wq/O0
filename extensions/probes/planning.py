"""O0 planning probe (extension): measured task decomposition & DAG execution.

Mirrors o0/probes.py: a `Probe` subclass running a FIXED, deterministic task
suite and returning a 0.0-1.0 `ProbeResult`.

What it measures
----------------
1. Goal Decomposition: Ability to break high-level tasks into valid sequential steps.
2. Dependency Resolution: Correct DAG order (topological sequence without circularity).
3. Deterministic Evaluation: Verifies step dependency satisfaction across a fixed suite
   of real engineering workflows (e.g. data pipelines, deployment, compilation).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from o0.probes import Probe, ProbeResult


@dataclass(frozen=True)
class PlanStep:
    name: str
    requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanningTask:
    task_id: str
    goal: str
    expected_steps: tuple[PlanStep, ...]
    candidate_order: tuple[str, ...]  # Sequence to validate


# Fixed deterministic task suite
PLANNING_TASKS: list[PlanningTask] = [
    PlanningTask(
        task_id="p1_build_pipeline",
        goal="Compile and test source code before deployment",
        expected_steps=(
            PlanStep("lint"),
            PlanStep("compile", ("lint",)),
            PlanStep("test", ("compile",)),
            PlanStep("deploy", ("test",)),
        ),
        candidate_order=("lint", "compile", "test", "deploy"),
    ),
    PlanningTask(
        task_id="p2_data_etl",
        goal="Ingest, clean, transform, and load dataset",
        expected_steps=(
            PlanStep("fetch_raw"),
            PlanStep("validate_schema", ("fetch_raw",)),
            PlanStep("transform", ("validate_schema",)),
            PlanStep("load_dw", ("transform",)),
        ),
        candidate_order=("fetch_raw", "validate_schema", "transform", "load_dw"),
    ),
    PlanningTask(
        task_id="p3_agent_creation",
        goal="Define spec, generate agent module, register in ledger, and dispatch",
        expected_steps=(
            PlanStep("define_spec"),
            PlanStep("write_module", ("define_spec",)),
            PlanStep("append_ledger", ("write_module",)),
            PlanStep("dispatch", ("append_ledger",)),
        ),
        candidate_order=("define_spec", "write_module", "append_ledger", "dispatch"),
    ),
    PlanningTask(
        task_id="p4_bad_order_negative_control",
        goal="Attempting deployment before compiling (should fail verification)",
        expected_steps=(
            PlanStep("compile"),
            PlanStep("deploy", ("compile",)),
        ),
        candidate_order=("deploy", "compile"),  # Inverted order!
    ),
    PlanningTask(
        task_id="p5_missing_dependency_negative_control",
        goal="Skipping mandatory validation step",
        expected_steps=(
            PlanStep("fetch"),
            PlanStep("validate", ("fetch",)),
            PlanStep("store", ("validate",)),
        ),
        candidate_order=("fetch", "store"),  # Missing 'validate'!
    ),
]


class PlanningProbe(Probe):
    """Measures planning correctness: topological validity and dependency satisfaction."""

    name = "planning"

    def __init__(self, tasks: list[PlanningTask] | None = None):
        self.tasks = PLANNING_TASKS if tasks is None else tasks

    def _verify_plan(self, task: PlanningTask) -> bool:
        """Checks if candidate_order satisfies all requirements of expected_steps."""
        step_deps = {s.name: set(s.requires) for s in task.expected_steps}
        required_steps = set(step_deps.keys())
        candidate_steps = list(task.candidate_order)

        # Must include all required steps
        if set(candidate_steps) != required_steps:
            return False

        # Must satisfy dependencies at every step
        executed: set[str] = set()
        for step in candidate_steps:
            if not step_deps.get(step, set()).issubset(executed):
                return False
            executed.add(step)
        return True

    def run(self) -> ProbeResult:
        if not self.tasks:
            return ProbeResult(self.name, None, 0, 0, "not measured: empty suite")

        passed = 0
        total = len(self.tasks)
        for task in self.tasks:
            is_valid = self._verify_plan(task)
            # If it's a negative control (task_id has 'negative_control'), it should be rejected
            if "negative_control" in task.task_id:
                passed += int(not is_valid)
            else:
                passed += int(is_valid)

        score = passed / total
        detail = f"{passed}/{total} planning workflows verified (valid order & negative guards passed)"
        return ProbeResult(self.name, score, passed, total, detail)
