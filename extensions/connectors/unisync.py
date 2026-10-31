"""O0's client for the shared UniSync ledger (``unisync/1``, spec in LESTINXOR-AGENT ``docs/UNISYNC.md``).

O0 is registered as an orchestrator. This client may post only:

- ``heartbeat`` and ``memory.write`` (status, always valid for a registered agent),
- ``escalate`` (asks Jonny for attention),
- ``task.request`` — always with ``requires_approval: true`` and a task id derived from the shared
  head, so it can never collide with an existing task or skip Jonny's approval.

It never posts claims, results or approval decisions. Before writing it re-verifies the head
entry's digest and refuses to build on a tampered head. Digests are byte-identical to Lestinxor's
reference ``envelope_digest`` and Sebastian's client.

Opt-in: only active when ``UNISYNC_SUPABASE_URL`` (https) and ``UNISYNC_SUPABASE_KEY`` (O0's own
gateway token, never the service-role key) are set. Constitution value 8: the key is read from the
environment and never written to the ledger, memory or source.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = "unisync/1"
GENESIS = "0" * 64
SENDER = "o0"
TABLE = "unisync_events"
REQUIRED: Mapping[str, tuple[str, ...]] = {
    "heartbeat": (),
    "memory.write": ("key", "value"),
    "escalate": ("reason",),
    "task.request": ("title",),
}

Opener = Callable[..., Any]


class UnisyncError(RuntimeError):
    """A post was refused locally, or the shared head failed verification."""


def envelope_digest(
    seq: int, sender: str, kind: str, task_id: str, body: Mapping[str, Any], prev: str
) -> str:
    """SHA-256 of the canonical envelope (timestamp excluded); identical to the reference."""
    payload = {"v": PROTOCOL_VERSION, "seq": seq, "sender": sender, "kind": kind, "task_id": task_id}
    payload.update({"body": dict(body), "prev": prev})
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True)
class Posted:
    """One envelope O0 wrote."""

    seq: int
    kind: str
    task_id: str
    digest: str


class UnisyncClient:
    """Writes O0's envelopes at the shared head; retries when another agent wins the race."""

    def __init__(
        self,
        url: str,
        key: str,
        opener: Opener | None = None,
        clock: Callable[[], float] = time.time,
        timeout: float = 15.0,
        retries: int = 5,
    ) -> None:
        if not url.startswith("https://"):
            raise UnisyncError("UNISYNC_SUPABASE_URL must be an https:// URL")
        if not key:
            raise UnisyncError("UNISYNC_SUPABASE_KEY is empty")
        self.endpoint = url.rstrip("/") + "/rest/v1/" + TABLE
        self._headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        self.opener: Opener = opener or urllib.request.urlopen
        self.clock = clock
        self.timeout = timeout
        self.retries = retries

    def __repr__(self) -> str:  # never show the key
        return f"UnisyncClient(endpoint={self.endpoint!r})"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **kw: Any) -> UnisyncClient | None:
        """A client from ``UNISYNC_SUPABASE_URL`` and ``UNISYNC_SUPABASE_KEY``; None if either is unset."""
        env = os.environ if env is None else env
        url, key = env.get("UNISYNC_SUPABASE_URL", ""), env.get("UNISYNC_SUPABASE_KEY", "")
        return cls(url, key, **kw) if url and key else None

    def _request(self, method: str, url: str, payload: Any = None, extra: Mapping[str, str] | None = None) -> Any:
        data = None if payload is None else json.dumps(payload, default=str).encode()
        req = urllib.request.Request(url, data=data, method=method, headers={**self._headers, **(extra or {})})
        with self.opener(req, timeout=self.timeout) as resp:  # noqa: S310 - https enforced above
            raw = resp.read()
        return json.loads(raw) if raw else None

    def head(self) -> tuple[int, str]:
        """``(next seq, prev digest)`` after re-checking the head entry's digest."""
        query = urllib.parse.urlencode(
            {"select": "v,seq,sender,kind,task_id,body,prev,digest", "order": "seq.desc", "limit": "1"}
        )
        try:
            rows = self._request("GET", f"{self.endpoint}?{query}") or []
        except urllib.error.HTTPError as exc:
            raise UnisyncError(f"ledger read failed: HTTP {exc.code}") from exc
        if not rows:
            return 0, GENESIS
        row = rows[0]
        expect = envelope_digest(row["seq"], row["sender"], row["kind"], row["task_id"], row["body"], row["prev"])
        if row.get("v") != PROTOCOL_VERSION or row["digest"] != expect:
            raise UnisyncError(f"ledger head at seq {row['seq']} fails verification; not writing on top of it")
        return int(row["seq"]) + 1, str(row["digest"])

    def post(self, kind: str, task_id: str = "", **body: Any) -> Posted:
        """Append one envelope at the shared head. ``task.request`` goes through ``request_task``."""
        if kind not in REQUIRED:
            raise UnisyncError(f"o0's client may not post {kind!r}")
        if kind == "task.request" and (not task_id or body.get("requires_approval") is not True):
            raise UnisyncError("use request_task(): O0's task requests always require Jonny's approval")
        if kind != "task.request" and task_id:
            raise UnisyncError(f"{kind} from O0 carries no task_id")
        missing = [k for k in REQUIRED[kind] if k not in body]
        if missing:
            raise UnisyncError(f"{kind} missing body field(s): {', '.join(missing)}")
        return self._write(kind, lambda prev: task_id, body)

    def request_task(self, title: str, **body: Any) -> Posted:
        """Post a ``task.request`` that needs Jonny's approval, with a collision-free id.

        The id is derived from the head it is written on (``o0-`` + 16 hex of sha256(prev, title)),
        and ``prev`` is unique in the ledger, so the id can never already exist.
        """
        if not title.strip():
            raise UnisyncError("task.request needs a non-empty title")
        body = {**body, "title": title, "requires_approval": True, "origin": SENDER}

        def task_id_for(prev: str) -> str:
            return "o0-" + hashlib.sha256(f"{prev}\n{title}".encode()).hexdigest()[:16]

        return self._write("task.request", task_id_for, body)

    def _write(self, kind: str, task_id_for: Callable[[str], str], body: Mapping[str, Any]) -> Posted:
        for _ in range(self.retries):
            seq, prev = self.head()
            task_id = task_id_for(prev)
            digest = envelope_digest(seq, SENDER, kind, task_id, body, prev)
            row = {
                "v": PROTOCOL_VERSION, "seq": seq, "sender": SENDER, "kind": kind, "task_id": task_id,
                "body": dict(body), "prev": prev, "digest": digest, "ts": self.clock(),
            }  # fmt: skip
            try:
                self._request("POST", self.endpoint, row, {"Prefer": "return=minimal"})
            except urllib.error.HTTPError as exc:
                if exc.code == 409:  # another agent wrote at this seq first; re-read the head
                    continue
                raise UnisyncError(f"ledger write failed: HTTP {exc.code}") from exc
            return Posted(seq, kind, task_id, digest)
        raise UnisyncError(f"gave up after {self.retries} concurrent-write conflicts")

    def heartbeat(self, **body: Any) -> Posted:
        return self.post("heartbeat", **body)

    def remember(self, key: str, value: Any) -> Posted:
        """Write ``value`` under ``key`` in O0's own memory scope."""
        return self.post("memory.write", key=key, value=value, scope=SENDER)

    def escalate(self, reason: str, **body: Any) -> Posted:
        return self.post("escalate", reason=reason, **body)
