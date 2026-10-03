"""Tests for PlanningProbe (extensions/probes/planning.py)."""
from __future__ import annotations

from o0.probes import ProbeResult

from extensions.probes import EXTENSION_PROBES, run_extension_probes
from extensions.probes.planning import (
    PLANNING_TASKS,
    PlanStep,
    PlanningProbe,
    PlanningTask,
)


def test_planning_probe_registered():
    assert "planning" in EXTENSION_PROBES
    assert EXTENSION_PROBES["planning"] is PlanningProbe


def test_planning_probe_returns_valid_score():
    probe = PlanningProbe()
    result = probe.run()
    assert isinstance(result, ProbeResult)
    assert result.name == "planning"
    assert result.score == 1.0
    assert result.passed == 5
    assert result.total == 5
    assert "planning workflows verified" in result.detail


def test_planning_detects_cycle_or_invalid_sequence():
    bad_task = PlanningTask(
        task_id="bad_manual",
        goal="Test invalid dependency",
        expected_steps=(
            PlanStep("a"),
            PlanStep("b", ("a",)),
        ),
        candidate_order=("b", "a"),
    )
    probe = PlanningProbe(tasks=[bad_task])
    result = probe.run()
    assert result.passed == 0
    assert result.score == 0.0


def test_empty_tasks_returns_none():
    probe = PlanningProbe(tasks=[])
    res = probe.run()
    assert res.score is None
    assert "not measured" in res.detail


def test_run_extension_probes_includes_planning():
    results = run_extension_probes()
    probe_names = [r.name for r in results]
    assert "research" in probe_names
    assert "planning" in probe_names
