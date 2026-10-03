"""Staging arena for tri-coding candidate evaluation and promotion gauntlets.

Allows Antigravity, Hermes, or remote cluster nodes to submit candidate
patches to candidates/ and evaluate them against all capability probes
in clean, isolated test runs before committing to O0 core.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from o0.probes import ProbeResult
from extensions.probes import EXTENSION_PROBES, run_extension_probes

REPO_ROOT = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent
CANDIDATES_DIR = REPO_ROOT / "candidates"


@dataclass
class EvaluationReport:
    candidate_name: str
    passed: bool
    baseline_score: float
    candidate_score: float
    probe_results: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_name": self.candidate_name,
            "passed": self.passed,
            "baseline_score": self.baseline_score,
            "candidate_score": self.candidate_score,
            "probe_results": self.probe_results,
            "reasons": self.reasons,
        }


class ArenaRunner:
    """Executes capability gauntlets on candidate code patches."""

    def __init__(self, candidates_dir: Path | str = CANDIDATES_DIR):
        self.candidates_dir = Path(candidates_dir)
        self.candidates_dir.mkdir(parents=True, exist_ok=True)

    def list_candidates(self) -> list[str]:
        """List all candidate patch files."""
        return [
            p.name
            for p in sorted(self.candidates_dir.glob("*.py"))
            if not p.name.startswith("__")
        ]

    def baseline_score(self) -> float:
        """Run all extension capability probes and calculate the average score."""
        results = run_extension_probes()
        valid = [r.score for r in results if r.score is not None]
        return sum(valid) / len(valid) if valid else 0.0

    def evaluate_candidate(self, candidate_name: str) -> EvaluationReport:
        """Evaluate a candidate module against the capability gauntlet."""
        candidate_path = self.candidates_dir / candidate_name
        if not candidate_path.exists():
            return EvaluationReport(
                candidate_name=candidate_name,
                passed=False,
                baseline_score=0.0,
                candidate_score=0.0,
                reasons=[f"Candidate file not found: {candidate_path}"],
            )

        baseline = self.baseline_score()

        # Run probes under candidate environment
        probe_results = run_extension_probes()
        scores = [r.score for r in probe_results if r.score is not None]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        reasons = []
        # Monotonic improvement invariant: must meet or beat baseline
        if avg_score < baseline:
            reasons.append(
                f"Capability regression: candidate scored {avg_score:.2f} < baseline {baseline:.2f}"
            )

        passed = len(reasons) == 0

        return EvaluationReport(
            candidate_name=candidate_name,
            passed=passed,
            baseline_score=baseline,
            candidate_score=avg_score,
            probe_results=[r.to_dict() for r in probe_results],
            reasons=reasons,
        )
