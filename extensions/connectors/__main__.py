"""CLI: python -m extensions.connectors status | heartbeat | dispatch TARGET TITLE [--detail TEXT]."""

from __future__ import annotations

import argparse
import json
import sys

from .dispatch import Dispatcher, DispatchError
from .github import github_stack
from .unisync import UnisyncClient, UnisyncError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m extensions.connectors")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="probe every project repo on GitHub")
    sub.add_parser("heartbeat", help="post an O0 heartbeat to UniSync")
    d = sub.add_parser("dispatch", help="request a task from another agent (needs Jonny's approval)")
    d.add_argument("target")
    d.add_argument("title")
    d.add_argument("--detail", default="")
    args = parser.parse_args(argv)

    if args.cmd == "status":
        print(json.dumps([c.status() for c in github_stack()], indent=2))
        return 0
    client = UnisyncClient.from_env()
    if client is None:
        print("UniSync is not configured: set UNISYNC_SUPABASE_URL and UNISYNC_SUPABASE_KEY", file=sys.stderr)
        return 2
    try:
        if args.cmd == "heartbeat":
            posted = client.heartbeat(note="manual")
            print(json.dumps({"seq": posted.seq, "digest": posted.digest}))
            return 0
        result = Dispatcher(client).dispatch(args.target, args.title, args.detail)
    except (UnisyncError, DispatchError) as exc:
        print(f"o0: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
