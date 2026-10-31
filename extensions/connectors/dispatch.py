"""Human-gated task dispatch from O0 to the other agents, over UniSync.

``Dispatcher.dispatch`` never runs another agent and never changes another repo. It posts a
``task.request`` addressed to a registered agent with ``requires_approval: true``; the task stays
``awaiting_approval`` until Jonny posts the ``approval.decision`` (only the owner can), and only then
can the target agent claim it. Constitution value 5 (preserve operator intent) holds by
construction: O0 proposes, Jonny decides.
"""

from __future__ import annotations

from typing import Any

from .unisync import UnisyncClient, UnisyncError

# Agents O0 may hand work to: the UniSync workers plus the other orchestrator.
TARGETS = frozenset({"sebastian", "lestinxor", "hermes", "jules", "claude"})
MAX_TITLE = 200
MAX_DETAIL = 4000


class DispatchError(ValueError):
    """A dispatch was refused before anything was posted."""


class Dispatcher:
    def __init__(self, client: UnisyncClient) -> None:
        self.client = client

    @classmethod
    def from_env(cls, **kw: Any) -> Dispatcher | None:
        """A dispatcher when UniSync is configured, else None (fail-open)."""
        client = UnisyncClient.from_env(**kw)
        return cls(client) if client else None

    def dispatch(self, target: str, title: str, detail: str = "", repo: str = "") -> dict:
        target = target.strip().lower()
        if target not in TARGETS:
            raise DispatchError(f"unknown target {target!r}; one of {', '.join(sorted(TARGETS))}")
        title = " ".join(title.split())
        if not title:
            raise DispatchError("title must not be empty")
        if len(title) > MAX_TITLE or len(detail) > MAX_DETAIL:
            raise DispatchError(f"title is capped at {MAX_TITLE} chars and detail at {MAX_DETAIL}")
        body: dict[str, Any] = {"assignee": target}
        if detail:
            body["detail"] = detail
        if repo:
            body["repo"] = repo
        try:
            posted = self.client.request_task(title, **body)
        except UnisyncError as exc:
            return {"target": target, "ok": False, "detail": str(exc)}
        return {
            "target": target,
            "ok": True,
            "task_id": posted.task_id,
            "seq": posted.seq,
            "status": "awaiting_approval",
            "detail": "posted; waiting for Jonny's approval before anyone can claim it",
        }
