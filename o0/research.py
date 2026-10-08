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
from datetime import datetime, timezone
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
INDEX_VERSION = 2
HORIZONTAL_ROOT = Path(os.environ.get(
    "HORIZONTAL_ROOT", "C:/Users/jonny/OneDrive/Desktop/HORIZONTAL"
))

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
_STATION_PATH = re.compile(r"(?:^|[/\\])STATIONS[/\\]([^/\\]+)", re.IGNORECASE)


def _metadata_value(value: object, default: str = "") -> str:
    """Normalize frontmatter scalars without leaking parser-specific types."""
    if value is None:
        return default
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value).strip().strip("'\"") or default


def _parse_frontmatter(text: str) -> dict:
    """Parse the simple YAML subset used by O0-DIRECTORY notes."""
    m = _FM_RE.match(text)
    if not m:
        return {}
    fm: dict = {}
    list_key: str | None = None
    for line in m.group(1).splitlines():
        stripped = line.strip()
        if stripped.startswith("-") and list_key:
            fm.setdefault(list_key, []).append(stripped[1:].strip().strip("'\""))
            continue
        if ":" not in line:
            list_key = None
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if not key:
            list_key = None
            continue
        if not val:
            fm[key] = []
            list_key = key
        elif val.startswith("[") and val.endswith("]"):
            fm[key] = [item.strip().strip("'\"")
                       for item in val[1:-1].split(",") if item.strip()]
            list_key = None
        else:
            fm[key] = val.strip("'\"")
            list_key = None
    return fm


def _extract_wikilinks(text: str) -> list[str]:
    return [m.strip() for m in _WIKILINK_RE.findall(text)]


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
            rel = md.relative_to(self.vault_path).as_posix()
            station_match = _STATION_PATH.search(rel)
            station = _metadata_value(fm.get("station"),
                                      station_match.group(1) if station_match else "")
            tags = fm.get("tags", [])
            if not isinstance(tags, list):
                tags = [tags]
            quick_paths = fm.get("quick_paths", [])
            if not isinstance(quick_paths, list):
                quick_paths = [quick_paths]
            title = _metadata_value(fm.get("title"), md.stem)
            created = _metadata_value(
                fm.get("timestamp") or fm.get("created_at") or fm.get("created")
            )
            notes.append({
                "path": str(md),
                "rel": rel,
                "title": title,
                "station": station.upper(),
                "priority": _priority(fm.get("priority")),
                "quick_paths": [_metadata_value(x) for x in quick_paths],
                "category": _metadata_value(fm.get("category", "")),
                "authors": _metadata_value(fm.get("authors", "")),
                "algo_focus": _metadata_value(fm.get("algo_focus", "")),
                "status": _metadata_value(fm.get("status", "")),
                "arxiv_id": _metadata_value(fm.get("arxiv_id", "")),
                "created": created,
                "tags": [_metadata_value(x) for x in tags],
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
            json.dumps({"version": INDEX_VERSION, "vault": str(self.vault_path),
                        "notes": self.notes}, indent=2), encoding="utf-8")
        return self.index_path

    def load(self) -> bool:
        if not self.index_path.exists():
            return False
        data = json.loads(self.index_path.read_text(encoding="utf-8"))
        if data.get("version") != INDEX_VERSION:
            self.notes = []
            return False
        indexed_root = data.get("vault")
        if not indexed_root or _canonical_path(indexed_root) != _canonical_path(self.vault_path):
            self.notes = []
            return False
        self.notes = data.get("notes", [])
        return True

    # -- search -------------------------------------------------------------
    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Rank O0 memories by lexical match, spatial links, priority and recency."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")
        q = _tokens(query)
        if not q:
            return []

        station_hits: set[str] = set()
        station_names = {
            "ML": {"ml", "machine learning", "model", "architecture", "neural"},
            "TESTS": {"test", "tests", "benchmark", "probe", "verification"},
            "REASONING": {"reasoning", "reason", "mcts", "adas", "cognitive"},
            "SYSTEMS": {"system", "systems", "cluster", "ipc", "distributed"},
            "TASKS": {"task", "tasks", "report", "execution"},
        }
        for station, terms in station_names.items():
            if any(q & _tokens(term) for term in terms):
                station_hits.add(station)

        scored: list[tuple[float, str, dict]] = []
        for n in self.notes:
            fields = {
                "title": _tokens(n.get("title", "").replace("_", " ")),
                "abstract": _tokens(n.get("abstract", "")),
                "tags": _tokens(" ".join(n.get("tags", []))),
                "station": _tokens(n.get("station", "")),
                "links": _tokens((" ".join(n.get("wikilinks", [])) + " "
                                   + " ".join(n.get("quick_paths", []))).replace("_", " ")),
            }
            score = (3.0 * len(q & fields["title"])
                     + 1.0 * len(q & fields["abstract"])
                     + 2.0 * len(q & fields["tags"])
                     + 2.0 * len(q & fields["station"])
                     + 1.5 * len(q & fields["links"]))
            if not score:
                continue
            if n.get("station") in station_hits:
                score += 3.0
            score += min(max(n.get("priority", 0), 0), 10) * 0.1
            score += _recency_boost(n.get("created", ""))
            scored.append((score, n.get("rel", ""), n))
        scored.sort(key=lambda item: (-item[0], item[1].casefold()))
        results = []
        for score, _rel, note in scored[:limit]:
            result = dict(note)
            result["score"] = round(score, 4)
            results.append(result)
        return results

    def topics(self) -> dict:
        """Aggregate counts by station, category, and algorithm focus."""
        cats: dict[str, int] = {}
        focuses: dict[str, int] = {}
        stations: dict[str, int] = {}
        for n in self.notes:
            if n["category"]:
                cats[n["category"]] = cats.get(n["category"], 0) + 1
            if n["algo_focus"]:
                focuses[n["algo_focus"]] = focuses.get(n["algo_focus"], 0) + 1
            if n.get("station"):
                stations[n["station"]] = stations.get(n["station"], 0) + 1
        return {"categories": cats, "algo_focus": focuses, "stations": stations}

    def stats(self) -> dict:
        return {
            "vault": str(self.vault_path),
            "notes_indexed": len(self.notes),
            "index_path": str(self.index_path),
        }


def _canonical_path(path: Path | str) -> str:
    """Normalize equivalent Windows/POSIX spellings for persisted root checks."""
    return os.path.normcase(str(Path(path).resolve()))


def _priority(value: object) -> int:
    try:
        return max(0, min(10, int(str(value).strip())))
    except (TypeError, ValueError):
        return 0


def _recency_boost(value: str) -> float:
    if not value:
        return 0.0
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (datetime.now(timezone.utc) - timestamp).total_seconds() / 86400)
        return round(0.5 * (0.5 ** (age_days / 30.0)), 3)
    except (ValueError, OverflowError, TypeError):
        return 0.0


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
