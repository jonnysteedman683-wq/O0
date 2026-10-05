"""
Cluster Configuration for Multi-Computer O0 Deployment.
Manages node identities, authentication tokens, network endpoints, and peer registries.
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ClusterConfig:
    node_id: str = field(default_factory=lambda: f"node_{socket.gethostname().lower()}")
    role: str = "HYBRID"  # "PRIMARY", "WORKER", or "HYBRID"
    listen_host: str = "0.0.0.0"
    listen_port: int = 8990
    auth_token: str = "o0-cluster-secret"
    peers: List[str] = field(default_factory=list)  # e.g., ["http://192.168.1.105:8990"]
    vault_path: Optional[str] = None
    max_concurrent_tasks: int = 4

    @classmethod
    def load(cls, config_path: Optional[Path | str] = None) -> ClusterConfig:
        """Loads configuration from JSON file or environment variables."""
        path = Path(config_path) if config_path else Path("cluster_config.json")
        data: Dict[str, Any] = {}

        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {}

        # Environment variable overrides
        if "O0_NODE_ID" in os.environ:
            data["node_id"] = os.environ["O0_NODE_ID"]
        if "O0_NODE_ROLE" in os.environ:
            data["role"] = os.environ["O0_NODE_ROLE"]
        if "O0_LISTEN_HOST" in os.environ:
            data["listen_host"] = os.environ["O0_LISTEN_HOST"]
        if "O0_LISTEN_PORT" in os.environ:
            data["listen_port"] = int(os.environ["O0_LISTEN_PORT"])
        if "O0_AUTH_TOKEN" in os.environ:
            data["auth_token"] = os.environ["O0_AUTH_TOKEN"]
        if "O0_CLUSTER_PEERS" in os.environ:
            data["peers"] = [p.strip() for p in os.environ["O0_CLUSTER_PEERS"].split(",") if p.strip()]

        return cls(
            node_id=data.get("node_id", f"node_{socket.gethostname().lower()}"),
            role=data.get("role", "HYBRID"),
            listen_host=data.get("listen_host", "0.0.0.0"),
            listen_port=int(data.get("listen_port", 8990)),
            auth_token=data.get("auth_token", "o0-cluster-secret"),
            peers=data.get("peers", []),
            vault_path=data.get("vault_path"),
            max_concurrent_tasks=int(data.get("max_concurrent_tasks", 4)),
        )

    def save(self, config_path: Optional[Path | str] = None) -> Path:
        """Saves current configuration to JSON file."""
        path = Path(config_path) if config_path else Path("cluster_config.json")
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return path
