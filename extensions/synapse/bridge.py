"""Synapse: The Corpus Callosum inter-orchestrator bridge for O0.

Facilitates high-speed, fail-open communication, task delegation,
and capability verification handoffs between Left Hemisphere (Antigravity),
Right Hemisphere (Hermes), and O0.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent
SYNAPSE_DIR = REPO_ROOT / "state" / "synapse"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class SynapseMessage:
    sender: str
    recipient: str
    topic: str
    payload: dict[str, Any]
    ts: str = field(default_factory=_now_iso)
    msg_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "msg_id": self.msg_id or f"{self.sender}_{self.topic}_{self.ts}",
            "sender": self.sender,
            "recipient": self.recipient,
            "topic": self.topic,
            "payload": self.payload,
            "ts": self.ts,
        }


class SynapseBridge:
    """Inter-orchestrator communication bus with atomic file-based mailboxes."""

    def __init__(self, root_dir: Path | str = SYNAPSE_DIR):
        self.root_dir = Path(root_dir)

    def _box(self, agent_name: str) -> Path:
        p = self.root_dir / f"inbox_{agent_name}"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def send(self, sender: str, recipient: str, topic: str, payload: dict[str, Any]) -> SynapseMessage:
        """Post a message into recipient's inbox atomically."""
        msg = SynapseMessage(sender=sender, recipient=recipient, topic=topic, payload=payload)
        inbox = self._box(recipient)
        safe_ts = msg.ts.replace(":", "-")
        fname = f"{safe_ts}_{sender}_{topic}.json"
        target = inbox / fname
        temp = inbox / f".tmp_{fname}"

        temp.write_text(json.dumps(msg.to_dict(), indent=2), encoding="utf-8")
        temp.replace(target)
        return msg

    def poll(self, agent_name: str, purge: bool = False) -> list[SynapseMessage]:
        """Read pending messages for an agent."""
        inbox = self._box(agent_name)
        messages: list[SynapseMessage] = []
        for file in sorted(inbox.glob("*.json")):
            if file.name.startswith("."):
                continue
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                messages.append(SynapseMessage(**data))
                if purge:
                    file.unlink(missing_ok=True)
            except Exception:
                continue
        return messages

    def broadcast_signal(self, sender: str, signal_name: str, details: dict[str, Any]) -> None:
        """Write a shared system signal observable by all orchestrators."""
        signals_dir = self.root_dir / "signals"
        signals_dir.mkdir(parents=True, exist_ok=True)
        sig_file = signals_dir / f"{signal_name}.json"
        sig_data = {
            "signal": signal_name,
            "sender": sender,
            "ts": _now_iso(),
            "details": details,
        }
        sig_file.write_text(json.dumps(sig_data, indent=2), encoding="utf-8")

    def read_signal(self, signal_name: str) -> dict[str, Any] | None:
        sig_file = self.root_dir / "signals" / f"{signal_name}.json"
        if not sig_file.exists():
            return None
        try:
            return json.loads(sig_file.read_text(encoding="utf-8"))
        except Exception:
            return None
