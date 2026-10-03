"""Tests for the Synapse bridge (extensions/synapse/bridge.py)."""
from __future__ import annotations

from pathlib import Path

from extensions.synapse import SynapseBridge


def test_synapse_send_and_poll(tmp_path: Path):
    bridge = SynapseBridge(root_dir=tmp_path / "synapse")
    
    # Send message from Antigravity to Hermes
    msg = bridge.send(
        sender="antigravity",
        recipient="hermes",
        topic="probe_verification",
        payload={"probe": "research", "score": 1.0, "status": "approved"}
    )
    assert msg.sender == "antigravity"
    assert msg.recipient == "hermes"

    # Hermes polls inbox
    hermes_msgs = bridge.poll("hermes")
    assert len(hermes_msgs) == 1
    assert hermes_msgs[0].topic == "probe_verification"
    assert hermes_msgs[0].payload["score"] == 1.0

    # Antigravity polls empty inbox
    agy_msgs = bridge.poll("antigravity")
    assert len(agy_msgs) == 0

    # Purge on poll
    purged = bridge.poll("hermes", purge=True)
    assert len(purged) == 1
    assert len(bridge.poll("hermes")) == 0


def test_synapse_broadcast_and_read_signal(tmp_path: Path):
    bridge = SynapseBridge(root_dir=tmp_path / "synapse")
    
    bridge.broadcast_signal(
        sender="hermes",
        signal_name="PROMOTION_CANDIDATE",
        details={"cycle": "v5-selfhost", "target": "o0/research.py"}
    )

    sig = bridge.read_signal("PROMOTION_CANDIDATE")
    assert sig is not None
    assert sig["sender"] == "hermes"
    assert sig["details"]["cycle"] == "v5-selfhost"

    missing = bridge.read_signal("NONEXISTENT_SIGNAL")
    assert missing is None
