"""GitHub-aware stack connectors: probe each project by its repo, not a local folder.

Mirrors ``o0.agency.StackConnector`` (same ``status``/``dispatch`` shape, honest and fail-open),
but works from any machine: ``status`` reads the repo's metadata and latest default-branch commit
from the GitHub REST API. Private repos (O0 itself, HORIZONTAL) need ``GITHUB_TOKEN`` or
``GH_TOKEN`` in the environment; without one they report "not visible" instead of failing.
``dispatch`` hands the task to a ``Dispatcher`` (UniSync, human-gated) when one is configured.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from o0.agency import Connector

if TYPE_CHECKING:
    from .dispatch import Dispatcher

API = "https://api.github.com"
OWNER = "jonnysteedman683-wq"
# name -> (repo, UniSync agent that works it, or "" when the project has no agent on the ledger)
STACK_REPOS: dict[str, tuple[str, str]] = {
    "SEBASTIAN": (f"{OWNER}/Sebastian", "sebastian"),
    "LESTINXOR": (f"{OWNER}/LESTINXOR-AGENT", "lestinxor"),
    "HERMES_HIVE": (f"{OWNER}/HERMES-HIVE", "hermes"),
    "SUPRIME": (f"{OWNER}/SUPRIME", ""),
    "HORIZONTAL": (f"{OWNER}/HORIZONTAL", ""),
    "SENTINEL": (f"{OWNER}/Sentinel", ""),
}

Opener = Callable[..., Any]


class GitHubConnector(Connector):
    """Honest availability probe for one project repo (fail-open)."""

    def __init__(
        self,
        name: str,
        repo: str,
        agent: str = "",
        dispatcher: Dispatcher | None = None,
        token: str | None = None,
        opener: Opener | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.name = name
        self.repo = repo
        self.agent = agent
        self.dispatcher = dispatcher
        self._token = token if token is not None else (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "")
        self.opener: Opener = opener or urllib.request.urlopen
        self.timeout = timeout

    def __repr__(self) -> str:  # never show the token
        return f"GitHubConnector(name={self.name!r}, repo={self.repo!r})"

    def _get(self, path: str) -> Any:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "O0-connector"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        req = urllib.request.Request(API + path, headers=headers)
        with self.opener(req, timeout=self.timeout) as resp:  # noqa: S310 - fixed https API host
            return json.loads(resp.read() or b"null")

    def status(self) -> dict:
        base: dict[str, Any] = {"name": self.name, "repo": self.repo, "agent": self.agent or None}
        try:
            meta = self._get(f"/repos/{self.repo}")
            branch = meta.get("default_branch", "main")
            commit = self._get(f"/repos/{self.repo}/commits/{branch}")
        except urllib.error.HTTPError as exc:
            detail = "not visible (private repo needs GITHUB_TOKEN)" if exc.code == 404 else f"HTTP {exc.code}"
            return {**base, "reachable": False, "detail": f"{detail} (fail-open)"}
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            return {**base, "reachable": False, "detail": f"unreachable: {exc} (fail-open)"}
        return {
            **base,
            "reachable": True,
            "detail": "reachable",
            "default_branch": branch,
            "pushed_at": meta.get("pushed_at"),
            "head": str(commit.get("sha", ""))[:7],
            "head_message": str((commit.get("commit") or {}).get("message", "")).splitlines()[0][:100]
            if (commit.get("commit") or {}).get("message")
            else "",
        }

    def dispatch(self, task: str) -> dict:
        if not self.agent:
            return {"name": self.name, "ok": False, "detail": "no agent works this repo on UniSync"}
        if self.dispatcher is None:
            return {"name": self.name, "ok": False, "detail": "UniSync not configured; nothing dispatched"}
        return self.dispatcher.dispatch(self.agent, task, repo=self.repo)


def github_stack(
    dispatcher: Dispatcher | None = None,
    repos: Mapping[str, tuple[str, str]] = STACK_REPOS,
    **kw: Any,
) -> list[GitHubConnector]:
    """One connector per project in ``repos``."""
    return [GitHubConnector(name, repo, agent, dispatcher, **kw) for name, (repo, agent) in repos.items()]
