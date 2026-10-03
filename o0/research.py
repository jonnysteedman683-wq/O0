"""O0 research index (v3): index the HORIZONTAL Obsidian vault for ML research.

Scans a vault (default: HORIZONTAL/03_Sources/ML_Research_Dossiers) for
markdown notes, parses YAML frontmatter (title, category, authors, algo_focus,
status), extracts wikilinks, and builds a persisted, searchable index.

Search is keyword/tag scored over title + abstract + tags (consistent with
v1 memory). No external deps: a minimal frontmatter parser handles the
`key: "value"` / `key: value` / `key: [a, b]` forms used in the vault.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

REPO_ROOT = Path(os.path.dirname(os.path.abspath(__file__))).parent

DEFAULT_VAULT = Path("C:/Users/jonny/OneDrive/Desktop/HORIZONTAL")
DEFAULT_ML_DIR = DEFAULT_VAULT / "03_Sources" / "ML_Research_Dossiers"
INDEX_PATH = REPO_ROOT / "state" / "vault_index.json"

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")


def _parse_frontmatter(text: str) -> dict:
    """Parse a YAML-ish frontmatter block into a dict (minimal, no deps)."""
    m = _FM_RE.match(text)
    if not m:
        return {}
    fm: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if not key:
            continue
        # list form: [a, b, c]
        if val.startswith("[") and val.endswith("]"):
            items = [x.strip().strip("'\"") for x in val[1:-1].split(",") if x.strip()]
            fm[key] = items
        else:
            fm[key] = val.strip("'\"")
    return fm


def _extract_wikilinks(text: str) -> list[str]:
    return [m.strip() for m in _WIKILINK_RE.findall(text)]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


class VaultIndex:
    """A persisted, searchable index of an Obsidian vault."""

    def __init__(self, vault_path: Path | str = DEFAULT_ML_DIR,
                 index_path: Path | str = INDEX_PATH):
        self.vault_path = Path(vault_path)
        self.index_path = Path(index_path)
        self.notes: list[dict] = []

    # -- indexing -----------------------------------------------------------
    def index(self) -> dict:
        """Scan the vault, parse notes, build the index. Returns stats."""
        if not self.vault_path.exists():
            raise FileNotFoundError(f"vault path not found: {self.vault_path}")
        notes: list[dict] = []
        for md in sorted(self.vault_path.rglob("*.md")):
            try:
                text = md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fm = _parse_frontmatter(text)
            # strip frontmatter for body text
            body = _FM_RE.sub("", text)
            title = fm.get("title") or md.stem
            notes.append({
                "path": str(md),
                "rel": str(md.relative_to(self.vault_path)),
                "title": title,
                "category": fm.get("category", ""),
                "authors": fm.get("authors", ""),
                "algo_focus": fm.get("algo_focus", ""),
                "status": fm.get("status", ""),
                "arxiv_id": fm.get("arxiv_id", ""),
                "tags": fm.get("tags", []),
                "wikilinks": _extract_wikilinks(text),
                "abstract": body.strip()[:1500],
            })
        self.notes = notes
        self.save()
        return self.stats()

    # -- persistence ---------------------------------------------------------
    def save(self) -> Path:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps({"vault": str(self.vault_path), "notes": self.notes},
                       indent=2), encoding="utf-8")
        return self.index_path

    def load(self) -> bool:
        if not self.index_path.exists():
            return False
        data = json.loads(self.index_path.read_text(encoding="utf-8"))
        self.notes = data.get("notes", [])
        return True

    # -- search -------------------------------------------------------------
    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Keyword/tag scored search over title + abstract + tags."""
        q = _tokens(query)
        scored: list[tuple[float, dict]] = []
        for n in self.notes:
            hay = _tokens(n["title"]) | _tokens(n["abstract"]) | set(n.get("tags", []))
            score = len(q & hay)
            if score:
                scored.append((score, n))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [n for _, n in scored[:limit]]

    def topics(self) -> dict:
        """Aggregate counts by category and algo_focus."""
        cats: dict[str, int] = {}
        focuses: dict[str, int] = {}
        for n in self.notes:
            if n["category"]:
                cats[n["category"]] = cats.get(n["category"], 0) + 1
            if n["algo_focus"]:
                focuses[n["algo_focus"]] = focuses.get(n["algo_focus"], 0) + 1
        return {"categories": cats, "algo_focus": focuses}

    def stats(self) -> dict:
        return {
            "vault": str(self.vault_path),
            "notes_indexed": len(self.notes),
            "index_path": str(self.index_path),
        }
