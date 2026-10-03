"""Tests for SynapseRPC network bridge (extensions/synapse/net_bridge.py)."""
from __future__ import annotations

import time

from extensions.synapse import SynapseRPCClient, SynapseRPCServer


def test_synapse_rpc_roundtrip():
    # Start ephemeral server on random high port
    server = SynapseRPCServer(host="127.0.0.1", port=8993)

    def echo_handler(params: dict) -> dict:
        return {"received": params.get("message", "")}

    server.register_method("echo", echo_handler)
    server.start()

    time.sleep(0.1)  # brief startup

    try:
        client = SynapseRPCClient(target_url="http://127.0.0.1:8993")
        res = client.call("echo", {"message": "hello node cluster"})
        assert res.get("ok") is True
        assert res.get("result", {}).get("received") == "hello node cluster"

        # Test unknown method
        bad = client.call("nonexistent_task", {})
        assert bad.get("ok") is False
        assert "Unknown method" in bad.get("error", "")
    finally:
        server.stop()
