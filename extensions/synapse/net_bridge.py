"""Networked Synapse daemon for multi-machine O0 cluster orchestration.

Enables physical nodes (e.g. GPU rigs, execution sandboxes, control laptops)
to communicate over TCP/HTTP with JSON-RPC payloads, broadcasting signals
and delegating tasks across computers.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable
from urllib.request import Request, urlopen


class SynapseRPCServer:
    """Lightweight HTTP JSON-RPC endpoint for inter-machine orchestrator sync."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8990):
        self.host = host
        self.port = port
        self.handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def register_method(self, name: str, handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self.handlers[name] = handler

    def start(self) -> None:
        handlers_ref = self.handlers

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Quiet logging

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                try:
                    payload = json.loads(body)
                    method = payload.get("method", "")
                    params = payload.get("params", {})
                    if method in handlers_ref:
                        result = handlers_ref[method](params)
                        resp = {"ok": True, "result": result}
                    else:
                        resp = {"ok": False, "error": f"Unknown method: {method}"}
                except Exception as exc:
                    resp = {"ok": False, "error": str(exc)}

                data = json.dumps(resp).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = HTTPServer((self.host, self.port), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()


class SynapseRPCClient:
    """Client for dispatching tasks and polling cluster nodes over network."""

    def __init__(self, target_url: str = "http://127.0.0.1:8990"):
        self.target_url = target_url

    def call(self, method: str, params: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
        payload = json.dumps({"method": method, "params": params}).encode("utf-8")
        req = Request(
            self.target_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)
