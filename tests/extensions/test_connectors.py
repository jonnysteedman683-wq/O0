"""O0 connectors: UniSync client, GitHub stack probes and human-gated dispatch. Offline."""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any

import pytest

from extensions.connectors import (
    STACK_REPOS,
    Dispatcher,
    DispatchError,
    GitHubConnector,
    UnisyncClient,
    UnisyncError,
    github_stack,
)
from extensions.connectors import __main__ as cli
from extensions.connectors.unisync import GENESIS, envelope_digest

URL = "https://example.supabase.co/functions/v1/unisync"

# Computed with LESTINXOR-AGENT's reference lestinxor.unisync.envelope_digest.
REF_TASK = "7c417be2c0e4298566cc1278db5334d578db09ad345c485f8e3f298b4d632218"
REF_HEARTBEAT = "dcf2b410b0eebb5f50f65ea356af63ea3ac252d5e066cee4d1e46ddfb5c25b60"


class Resp(io.BytesIO):
    def __enter__(self) -> Resp:
        return self

    def __exit__(self, *a: object) -> None:
        return None


class FakeLedger:
    """In-memory stand-in for the gateway: GET returns the head, POST appends (or 409s)."""

    def __init__(self, conflicts: int = 0) -> None:
        self.rows: list[dict[str, Any]] = []
        self.conflicts = conflicts
        self.headers: list[dict[str, str]] = []

    def __call__(self, req: Any, timeout: float) -> Resp:
        self.headers.append(dict(req.header_items()))
        if req.get_method() == "GET":
            return Resp(json.dumps(self.rows[-1:]).encode())
        if self.conflicts:
            self.conflicts -= 1
            raise urllib.error.HTTPError(req.full_url, 409, "conflict", {}, None)  # type: ignore[arg-type]
        self.rows.append(json.loads(req.data))
        return Resp(b"")


def client(ledger: FakeLedger) -> UnisyncClient:
    return UnisyncClient(URL, "tok-o0", opener=ledger, clock=lambda: 1.0)


def test_digest_matches_lestinxor_reference() -> None:
    body = {"title": "audit tasks.py", "requires_approval": True, "origin": "o0", "assignee": "sebastian"}
    assert envelope_digest(7, "o0", "task.request", "o0-abc", body, "f" * 64) == REF_TASK
    assert envelope_digest(0, "o0", "heartbeat", "", {}, GENESIS) == REF_HEARTBEAT


def test_heartbeat_and_memory_chain_correctly() -> None:
    led = FakeLedger()
    c = client(led)
    first = c.heartbeat()
    second = c.remember("flywheel", {"iteration": 3})
    assert (first.seq, second.seq) == (0, 1)
    assert led.rows[0]["digest"] == REF_HEARTBEAT
    assert led.rows[1]["prev"] == led.rows[0]["digest"]
    assert led.rows[1]["body"] == {"key": "flywheel", "value": {"iteration": 3}, "scope": "o0"}
    assert all(r["sender"] == "o0" for r in led.rows)


def test_key_is_sent_as_bearer_and_never_shown() -> None:
    led = FakeLedger()
    c = client(led)
    c.heartbeat()
    assert led.headers[0]["Authorization"] == "Bearer tok-o0"
    assert "tok-o0" not in repr(c)


def test_refuses_other_kinds_and_ungated_requests() -> None:
    c = client(FakeLedger())
    for kind in ("task.claim", "task.result", "approval.decision", "approval.request"):
        with pytest.raises(UnisyncError, match="may not post"):
            c.post(kind)
    with pytest.raises(UnisyncError, match="approval"):
        c.post("task.request", "o0-x", title="t")  # no requires_approval
    with pytest.raises(UnisyncError, match="no task_id"):
        c.post("heartbeat", "o0-x")
    with pytest.raises(UnisyncError, match="missing"):
        c.post("escalate")


def test_task_request_is_gated_and_collision_free() -> None:
    led = FakeLedger()
    c = client(led)
    a = c.request_task("audit tasks.py", assignee="sebastian")
    b = c.request_task("audit tasks.py", assignee="sebastian")  # same title, new head -> new id
    assert a.task_id != b.task_id and a.task_id.startswith("o0-") and len(a.task_id) == 19
    row = led.rows[0]
    assert row["body"]["requires_approval"] is True and row["body"]["origin"] == "o0"
    assert row["digest"] == envelope_digest(0, "o0", "task.request", a.task_id, row["body"], GENESIS)


def test_retries_on_conflict_then_gives_up() -> None:
    led = FakeLedger(conflicts=2)
    assert client(led).heartbeat().seq == 0
    led = FakeLedger(conflicts=9)
    with pytest.raises(UnisyncError, match="gave up"):
        UnisyncClient(URL, "k", opener=led, retries=3).heartbeat()


def test_refuses_to_build_on_a_tampered_head() -> None:
    led = FakeLedger()
    led.rows.append({"v": "unisync/1", "seq": 0, "sender": "x", "kind": "heartbeat",
                     "task_id": "", "body": {}, "prev": GENESIS, "digest": "0" * 64})  # fmt: skip
    with pytest.raises(UnisyncError, match="fails verification"):
        client(led).heartbeat()


def test_http_errors_surface_as_unisync_errors() -> None:
    def broken(req: Any, timeout: float) -> Any:
        raise urllib.error.HTTPError(req.full_url, 403, "forbidden", {}, None)  # type: ignore[arg-type]

    with pytest.raises(UnisyncError, match="HTTP 403"):
        client(broken).heartbeat()  # type: ignore[arg-type]


def test_from_env_is_opt_in_and_https_only() -> None:
    assert UnisyncClient.from_env({}) is None
    assert UnisyncClient.from_env({"UNISYNC_SUPABASE_URL": URL}) is None
    assert isinstance(UnisyncClient.from_env({"UNISYNC_SUPABASE_URL": URL, "UNISYNC_SUPABASE_KEY": "k"}), UnisyncClient)
    with pytest.raises(UnisyncError, match="https"):
        UnisyncClient("http://x", "k")


def test_dispatcher_posts_gated_requests_only_to_known_agents() -> None:
    led = FakeLedger()
    d = Dispatcher(client(led))
    out = d.dispatch("Sebastian", "  fix   B64  ", detail="fallback model", repo="o/r")
    assert out["ok"] and out["status"] == "awaiting_approval"
    assert led.rows[0]["body"] == {
        "assignee": "sebastian", "detail": "fallback model", "repo": "o/r",
        "title": "fix B64", "requires_approval": True, "origin": "o0",
    }  # fmt: skip
    with pytest.raises(DispatchError, match="unknown target"):
        d.dispatch("grok", "x")
    with pytest.raises(DispatchError, match="empty"):
        d.dispatch("sebastian", "   ")
    with pytest.raises(DispatchError, match="capped"):
        d.dispatch("sebastian", "x" * 201)


def test_dispatcher_fails_open_on_ledger_errors() -> None:
    led = FakeLedger(conflicts=99)
    out = Dispatcher(UnisyncClient(URL, "k", opener=led, retries=1)).dispatch("lestinxor", "x")
    assert out == {"target": "lestinxor", "ok": False, "detail": "gave up after 1 concurrent-write conflicts"}
    assert Dispatcher.from_env(env={}) is None


def gh(responses: dict[str, Any]) -> Any:
    def opener(req: Any, timeout: float) -> Resp:
        path = req.full_url.removeprefix("https://api.github.com")
        value = responses[path]
        if isinstance(value, int):
            raise urllib.error.HTTPError(req.full_url, value, "x", {}, None)  # type: ignore[arg-type]
        return Resp(json.dumps(value).encode())

    return opener


def test_github_status_reports_head_and_fails_open() -> None:
    ok = GitHubConnector("SEB", "o/seb", "sebastian", token="", opener=gh({
        "/repos/o/seb": {"default_branch": "main", "pushed_at": "2026-10-31T12:00:00Z"},
        "/repos/o/seb/commits/main": {"sha": "abcdef123", "commit": {"message": "fix: B53\n\nbody"}},
    }))  # fmt: skip
    s = ok.status()
    assert s["reachable"] and s["head"] == "abcdef1" and s["head_message"] == "fix: B53"
    hidden = GitHubConnector("O0", "o/o0", token="", opener=gh({"/repos/o/o0": 404})).status()
    assert not hidden["reachable"] and "GITHUB_TOKEN" in hidden["detail"]
    down = GitHubConnector("X", "o/x", token="", opener=gh({"/repos/o/x": 500})).status()
    assert down["detail"].startswith("HTTP 500")


def test_github_sends_token_only_as_header() -> None:
    seen: list[dict[str, str]] = []

    def opener(req: Any, timeout: float) -> Resp:
        seen.append(dict(req.header_items()))
        raise urllib.error.URLError("offline")

    c = GitHubConnector("X", "o/x", token="ghp_secret", opener=opener)
    assert c.status()["reachable"] is False
    assert seen[0]["Authorization"] == "Bearer ghp_secret" and "ghp_secret" not in repr(c)


def test_github_dispatch_routes_through_unisync_or_refuses() -> None:
    led = FakeLedger()
    seb = GitHubConnector("SEB", "o/seb", "sebastian", Dispatcher(client(led)), token="")
    assert seb.dispatch("run evals")["status"] == "awaiting_approval"
    assert led.rows[0]["body"]["repo"] == "o/seb"
    assert GitHubConnector("SUP", "o/sup", token="").dispatch("x")["ok"] is False
    assert GitHubConnector("SEB", "o/seb", "sebastian", token="").dispatch("x")["ok"] is False


def test_stack_covers_the_projects() -> None:
    names = {c.name for c in github_stack(token="")}
    assert names == set(STACK_REPOS)
    assert STACK_REPOS["SEBASTIAN"][1] == "sebastian"


def test_cli_needs_unisync_for_writes(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("UNISYNC_SUPABASE_URL", raising=False)
    monkeypatch.delenv("UNISYNC_SUPABASE_KEY", raising=False)
    assert cli.main(["heartbeat"]) == 2
    assert "not configured" in capsys.readouterr().err
