"""Git integration for O0's flywheel.

Each promotion becomes a real, SCOPED commit. We never `git add -A` — only
the O0-owned paths that are actually dirty are staged, so unrelated work in
the repo is never swept into a promotion commit.

Two commits per promotion (clean, auditable):
  1. source commit  — o0/, tests/, docs, skills/  (the improvement)
  2. ledger commit  — state/ (ledger.jsonl + memory.jsonl) referencing the
                      source commit hash, so the ledger record is durable.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# O0-owned paths (relative to repo root). state/ is handled separately.
SOURCE_PATHS = [
    "o0",
    "tests",
    "skills",
    "agents",
    "CONSTITUTION.md",
    "BLUEPRINT.md",
    "README.md",
    "IDEA.md",
    ".gitignore",
]
STATE_PATHS = ["state"]


def _git(args: list[str], cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=120
    )


def _rel(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def dirty_paths(paths: list[str], repo_root: Path = REPO_ROOT) -> list[str]:
    """Return the subset of `paths` that are modified or untracked."""
    dirty: list[str] = []
    for p in paths:
        if not (repo_root / p).exists():
            continue
        # untracked?
        r = _git(["ls-files", "--error-unmatch", p], cwd=repo_root)
        tracked = r.returncode == 0
        if not tracked:
            dirty.append(p)
            continue
        # modified?
        r = _git(["status", "--porcelain", "--", p], cwd=repo_root)
        if r.stdout.strip():
            dirty.append(p)
    return dirty


def commit(paths: list[str], message: str, repo_root: Path = REPO_ROOT) -> str | None:
    """Stage exactly `paths` and commit. Returns the commit hash, or None if
    there is nothing to commit (no dirty paths)."""
    dirty = dirty_paths(paths, repo_root=repo_root)
    if not dirty:
        return None
    _git(["add", "--", *dirty], cwd=repo_root)
    r = _git(["commit", "-m", message], cwd=repo_root)
    if r.returncode != 0:
        raise RuntimeError(f"git commit failed: {r.stderr.strip()}")
    # read back the hash to confirm (facts over vibes)
    h = _git(["rev-parse", "HEAD"], cwd=repo_root).stdout.strip()
    return h


def head(repo_root: Path = REPO_ROOT) -> str:
    return _git(["rev-parse", "HEAD"], cwd=repo_root).stdout.strip()


def is_clean(repo_root: Path = REPO_ROOT) -> bool:
    r = _git(["status", "--porcelain"], cwd=repo_root)
    return not r.stdout.strip()
