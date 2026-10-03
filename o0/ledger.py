"""Append-only provenance ledger for O0 (sha256-linked records).

Every event O0 records (promotion, rejection, observation) is written as a
sha256-bound JSON record. The receipt id of a record is the sha256 of its
own payload. History is append-only: we never rewrite an existing line.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Repo root is two levels up from this file: o0/ledger.py -> O0/
REPO_ROOT = Path(os.path.dirname(os.path.abspath(__file__))).parent

DEFAULT_LEDGER = REPO_ROOT / "state" / "ledger.jsonl"


def _sha256(text: str) -> str:
    """SHA-256 hex digest of a utf-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Ledger:
    """Append-only, self-verifying event ledger persisted as JSONL."""

    def __init__(self, path: Path | str = DEFAULT_LEDGER):
        self.path = Path(path)

    # -- helpers ------------------------------------------------------------
    def _ensure_dir(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _total_lines(self) -> int:
        if not self.path.exists():
            return 0
        with open(self.path, encoding="utf-8") as fh:
            return sum(1 for _ in fh)

    # -- write --------------------------------------------------------------
    def append(self, kind: str, payload: dict) -> dict:
        """Append a record. Returns the record with its sha256 receipt."""
        self._ensure_dir()
        record = {
            "kind": kind,
            "ts": _now_iso(),
            "seq": self._total_lines() + 1,
            **payload,
        }
        # Receipt binds the whole record (minus the receipt field itself).
        canonical = json.dumps(record, sort_keys=True)
        record["receipt"] = _sha256(canonical)
        line = json.dumps(record, sort_keys=True) + "\n"
        # Append without rewriting existing lines.
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line)
        return record

    # -- read + verify ------------------------------------------------------
    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        records: list[dict] = []
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                records.append(rec)
        return records

    def verify_integrity(self) -> tuple[bool, int, list[str]]:
        """Return (ok, records_checked, broken_receipts)."""
        records = self.read()
        broken: list[str] = []
        for rec in records:
            receipt = rec.pop("receipt", None)
            canonical = json.dumps(rec, sort_keys=True)
            if _sha256(canonical) != receipt:
                broken.append(f"seq={rec.get('seq')}")
            rec["receipt"] = receipt
        return (len(broken) == 0, len(records), broken)

    def tail(self, n: int = 5) -> list[dict]:
        return self.read()[-n:]
