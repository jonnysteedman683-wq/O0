"""O0-local directory index plus an explicit HORIZONTAL hybrid recall adapter.

The default index scans O0's own O0-DIRECTORY memory allocation. HORIZONTAL's
hybrid retriever is loaded only when a caller explicitly requests it (for
HORIZONTAL runtime or ML research).

Search is keyword/tag scored over title + abstract + tags (consistent with
v1 memory). No external deps: a minimal frontmatter parser handles the
`key: "value"` / `key: value` / `key: [a, b]` forms used in the vault.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(os.path.dirname(os.path.abspath(__file__))).parent

DEFAULT_VAULT = Path(os.environ.get(
    "O0_DIRECTORY_PATH", str(REPO_ROOT / "O0-DIRECTORY" / "O0-DIRECTORY")
))
DEFAULT_ML_DIR = DEFAULT_VAULT
DEFAULT_HORIZONTAL_SCRIPTS = Path(os.environ.get(
    "HORIZONTAL_SCRIPTS_DIR",
    "C:/Users/jonny/OneDrive/Desktop/HORIZONTAL/_Meta/Scripts",
))
INDEX_PATH = REPO_ROOT / "state" / "vault_index.json"
HORIZONTAL_ROOT = Path(os.environ.get(
    "HORIZONTAL_ROOT", "C:/Users/jonny/OneDrive/Desktop/HORIZONTAL"
))

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")


class HorizontalRecall:
    """Read-only O0 adapter to HORIZONTAL's hybrid vault retrieval engine.

    HORIZONTAL owns indexing and search semantics; O0 only forwards queries and
    returns its ranked result dictionaries. Set ``HORIZONTAL_SCRIPTS_DIR`` when
    the sibling repository is not at its standard Windows location.
    """

    def __init__(self, scripts_dir: Path | str = DEFAULT_HORIZONTAL_SCRIPTS,
                 engine=None):
        self.scripts_dir = Path(os.path.abspath(str(scripts_dir)))
        self._engine = engine

    def _get_engine(self):
        if self._engine is not None:
            return self._engine
        if not self.scripts_dir.is_dir():
            raise FileNotFoundError(
                f"HORIZONTAL scripts directory not found: {self.scripts_dir}; "
                "set HORIZONTAL_SCRIPTS_DIR to its _Meta/Scripts directory"
            )

        scripts_path = str(self.scripts_dir)
        already_present = scripts_path in sys.path
        if not already_present:
            sys.path.insert(0, scripts_path)
        try:
            from hybrid_semantic_search import VaultHybridSearchEngine
            self._engine = VaultHybridSearchEngine()
        except ImportError as exc:
            raise RuntimeError(
                f"could not load HORIZONTAL retrieval from {self.scripts_dir}: {exc}"
            ) from exc
        finally:
            if not already_present:
                sys.path.remove(scripts_path)
        return self._engine

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Return HORIZONTAL's hybrid-ranked recall results for ``query``."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        return self._get_engine().search(query, top_k=limit)


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
    """Tokenize + light stem (strip trailing s/es) for better recall."""
    out: set[str] = set()
    for tok in re.findall(r"[a-z0-9_]+", text.lower()):
        out.add(tok)
        if tok.endswith("ies") and len(tok) > 4:
            out.add(tok[:-3] + "y")
        elif tok.endswith("es") and len(tok) > 3:
            out.add(tok[:-2])
        elif tok.endswith("s") and len(tok) > 3:
            out.add(tok[:-1])
    return out


class VaultIndex:
    """A persisted, searchable index of a markdown memory directory."""

    def __init__(self, vault_path: Path | str = DEFAULT_ML_DIR,
                 index_path: Path | str = INDEX_PATH):
        self.vault_path = Path(vault_path)
        self.index_path = Path(index_path)
        self.notes: list[dict] = []

    # -- indexing -----------------------------------------------------------
    def index(self) -> dict:
        """Scan markdown beneath the configured memory root and persist index."""
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
        indexed_root = data.get("vault")
        if not indexed_root or _canonical_path(indexed_root) != _canonical_path(self.vault_path):
            self.notes = []
            return False
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


def _canonical_path(path: Path | str) -> str:
    """Normalize equivalent Windows/POSIX spellings for persisted root checks."""
    return os.path.normcase(str(Path(path).resolve()))


def running_from_horizontal(cwd: Path | str | None = None,
                            horizontal_root: Path | str = HORIZONTAL_ROOT) -> bool:
    """Return whether the current working directory is inside HORIZONTAL."""
    current = Path(cwd or Path.cwd()).resolve()
    root = Path(horizontal_root).resolve()
    try:
        current.relative_to(root)
        return True
    except ValueError:
        return False
