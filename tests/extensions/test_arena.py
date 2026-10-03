"""Tests for ArenaRunner (extensions/arena/runner.py)."""
from __future__ import annotations

from pathlib import Path

from extensions.arena import ArenaRunner


def test_arena_list_empty_candidates(tmp_path: Path):
    runner = ArenaRunner(candidates_dir=tmp_path / "candidates")
    assert runner.list_candidates() == []


def test_arena_baseline_calculation(tmp_path: Path):
    runner = ArenaRunner(candidates_dir=tmp_path / "candidates")
    score = runner.baseline_score()
    # Baseline combines ResearchProbe (0.75) and PlanningProbe (1.0) -> ~0.875
    assert 0.0 < score <= 1.0


def test_arena_evaluate_missing_candidate(tmp_path: Path):
    runner = ArenaRunner(candidates_dir=tmp_path / "candidates")
    report = runner.evaluate_candidate("nonexistent.py")
    assert report.passed is False
    assert "not found" in report.reasons[0]


def test_arena_evaluate_existing_candidate(tmp_path: Path):
    cand_dir = tmp_path / "candidates"
    cand_dir.mkdir()
    sample_candidate = cand_dir / "patch_001.py"
    sample_candidate.write_text("# Candidate placeholder\n", encoding="utf-8")

    runner = ArenaRunner(candidates_dir=cand_dir)
    assert runner.list_candidates() == ["patch_001.py"]

    report = runner.evaluate_candidate("patch_001.py")
    assert report.passed is True
    assert report.candidate_score >= report.baseline_score
    assert len(report.probe_results) >= 2
