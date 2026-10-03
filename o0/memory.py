"""O0 memory (v1): episodic + procedural, honest and verifiable.

- Episodic: append-only JSONL of experiences (remember/recall).
- Procedural: durable skills stored as markdown files under skills/.
- Recall at v1 is keyword/tag scoring (no embeddings yet) — honest, cheap,
  and extendable. v2+ can swap in semantic recall without changing the API.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(os.path.dirname(os.path.abspath(__file__))).parent

EPISODIC_PATH = REPO_ROOT / "state" / "memory.jsonl"
SKILLS_DIR = REPO_ROOT / "skills"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


class Memory:
    """Episodic + procedural memory for O0."""

    def __init__(self, episodic_path: Path | str = EPISODIC_PATH,
                 skills_dir: Path | str = SKILLS_DIR):
        self.episodic_path = Path(episodic_path)
        self.skills_dir = Path(skills_dir)

    # -- episodic -----------------------------------------------------------
    def remember(self, kind: str, content: str, tags: list[str] | None = None) -> dict:
        """Append an episodic memory. Returns the stored record."""
        self.episodic_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "kind": kind,
            "ts": _now_iso(),
            "content": content,
            "tags": tags or [],
        }
        with open(self.episodic_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def recall(self, query: str, limit: int = 5) -> list[dict]:
        """Keyword/tag-scored recall over episodic memory (v1)."""
        if not self.episodic_path.exists():
            return []
        q = _tokens(query)
        scored: list[tuple[float, dict]] = []
        with open(self.episodic_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                hay = _tokens(rec["content"]) | set(rec.get("tags", []))
                score = len(q & hay)
                if score:
                    scored.append((score, rec))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:limit]]

    def count(self) -> int:
        if not self.episodic_path.exists():
            return 0
        with open(self.episodic_path, encoding="utf-8") as fh:
            return sum(1 for _ in fh)

    # -- procedural ---------------------------------------------------------
    def write_skill(self, name: str, body: str) -> Path:
        """Persist a procedural skill as a markdown file under skills/."""
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^a-z0-9_-]", "-", name.lower())
        path = self.skills_dir / f"{safe}.md"
        path.write_text(body, encoding="utf-8")
        return path

    def list_skills(self) -> list[str]:
        if not self.skills_dir.exists():
            return []
        return sorted(p.name for p in self.skills_dir.glob("*.md"))

    def stats(self) -> dict:
        return {
            "episodic_records": self.count(),
            "procedural_skills": self.list_skills(),
        }
