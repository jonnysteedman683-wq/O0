"""O0 self-hosting autonomy (v5): O0 proposes, implements, verifies, and
promotes its OWN upgrades.

The capstone of the flywheel. Where v0-v4 ran a fixed promotion discipline,
v5 lets O0 author a candidate change to its own source, verify it against
the full gate + probe suite, and promote it ONLY if the capability score
strictly improves. A regression is rolled back and recorded.

Design (honest, bounded):
  - PROPOSE: a candidate is a small, self-contained, reversible source edit.
    At v5 the candidate is supplied by a pluggable `proposer` (an agent or
    human); self-authored proposals arrive in v5.1. We do NOT fake autonomy.
  - IMPLEMENT: apply the edit to a scratch copy, not the live tree.
  - VERIFY: run gates + probes on the scratch copy; measure the score.
  - PROMOTE: if score strictly improves AND gates pass, apply to live tree,
    commit, and record a sha256-bound ledger record. Else roll back.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import gitops
from .ledger import Ledger

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Candidate:
    """A proposed self-improvement: a reversible source edit."""
    name: str
    target: str          # repo-relative path, e.g. "o0/verify.py"
    old: str             # exact text to replace
    new: str             # replacement text
    rationale: str = ""


class SelfHost:
    """Propose -> implement -> verify -> promote (or roll back)."""

    def __init__(self, ledger: Ledger | None = None, commit: bool = True,
                 scorer: Callable[[Path], dict] | None = None):
        self.ledger = ledger or Ledger()
        self.commit = commit
        # scorer(root) -> {"score": float, "harness_ok": bool, "compile_ok": bool,
        #                  "probe_score": float}. Defaults to the real verifier.
        self._scorer = scorer or self._score_in

    # -- verify a candidate in a scratch copy ------------------------------
    def _score_in(self, root: Path) -> dict:
        """Run gates + probes against a copy of the repo at `root`."""
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "tests/"],
            cwd=str(root), capture_output=True, text=True, timeout=300)
        harness_ok = proc.returncode == 0
        compile_ok = True
        for py in (root / "o0").rglob("*.py"):
            r = subprocess.run([sys.executable, "-m", "py_compile", str(py)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                compile_ok = False
                break
        probe_proc = subprocess.run(
            [sys.executable, "-m", "o0.main", "--probes"],
            cwd=str(root), capture_output=True, text=True, timeout=300)
        probe_score = 0.0
        if probe_proc.returncode == 0:
            import json
            try:
                probes = json.loads(probe_proc.stdout)
                probe_score = sum(p["score"] for p in probes
                                  if p["score"] is not None)
            except (json.JSONDecodeError, KeyError):
                probe_score = 0.0
        gates_ok = sum([harness_ok, compile_ok])
        return {
            "harness_ok": harness_ok,
            "compile_ok": compile_ok,
            "probe_score": round(probe_score, 3),
            "score": round(gates_ok + probe_score, 3),
        }

    # -- the loop -----------------------------------------------------------
    def run(self, candidate: Candidate) -> dict:
        # 1. baseline score on the live tree
        baseline = self._scorer(REPO_ROOT)

        # 2. apply candidate to a scratch copy and score it
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp) / "o0"
            shutil.copytree(REPO_ROOT, scratch,
                            ignore=shutil.ignore_patterns(
                                ".git", ".venv", "__pycache__", "state"))
            target = scratch / candidate.target
            if not target.exists():
                return {"outcome": "reject", "reason": f"target missing: {candidate.target}",
                        "baseline": baseline}
            text = target.read_text(encoding="utf-8")
            if candidate.old not in text:
                return {"outcome": "reject", "reason": "old text not found",
                        "baseline": baseline}
            target.write_text(text.replace(candidate.old, candidate.new, 1),
                              encoding="utf-8")
            candidate_score = self._scorer(scratch)

        # 3. promote only if strictly better AND gates pass
        improved = (candidate_score["score"] > baseline["score"]
                    and candidate_score["harness_ok"]
                    and candidate_score["compile_ok"])
        outcome = "promote" if improved else "reject"

        commits: dict = {}
        if outcome == "promote" and self.commit:
            live = REPO_ROOT / candidate.target
            text = live.read_text(encoding="utf-8")
            live.write_text(text.replace(candidate.old, candidate.new, 1),
                            encoding="utf-8")
            src = gitops.commit([candidate.target],
                                f"O0 self-host: {candidate.name} (score {candidate_score['score']})")
            commits["source_commit"] = src

        rec = self.ledger.append(outcome, {
            "cycle": "v5-selfhost",
            "candidate": candidate.name,
            "target": candidate.target,
            "rationale": candidate.rationale,
            "baseline_score": baseline["score"],
            "candidate_score": candidate_score["score"],
            "baseline_probe": baseline["probe_score"],
            "candidate_probe": candidate_score["probe_score"],
            "commits": commits,
        })

        return {
            "outcome": outcome,
            "candidate": candidate.name,
            "baseline_score": baseline["score"],
            "candidate_score": candidate_score["score"],
            "baseline_probe": baseline["probe_score"],
            "candidate_probe": candidate_score["probe_score"],
            "ledger_receipt": rec["receipt"],
            "ledger_seq": rec["seq"],
            "commits": commits,
        }
