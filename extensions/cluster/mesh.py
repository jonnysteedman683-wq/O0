"""
Multi-Computer Mesh Network and Task Dispatcher for O0.
Discovers peers, health-checks nodes, and load balances tasks across machines.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from extensions.cluster.config import ClusterConfig
from extensions.synapse.net_bridge import SynapseRPCClient


@dataclass
class PeerStatus:
    url: str
    online: bool
    latency_ms: float = 0.0
    node_id: str = "unknown"
    role: str = "unknown"
    running_tasks: int = 0
    error: Optional[str] = None


class ClusterMesh:
    """Manages multi-node peer health and task dispatch across the network."""

    def __init__(self, config: Optional[ClusterConfig] = None):
        self.config = config or ClusterConfig.load()

    def check_peer_health(self, peer_url: str, timeout: float = 3.0) -> PeerStatus:
        """Pings a remote node and measures round-trip latency."""
        client = SynapseRPCClient(target_url=peer_url)
        t_start = time.perf_counter()
        try:
            resp = client.call(
                method="ping",
                params={"auth_token": self.config.auth_token},
                timeout=timeout,
            )
            latency = round((time.perf_counter() - t_start) * 1000, 2)
            if resp.get("ok"):
                res = resp.get("result", {})
                if "error" in res:
                    return PeerStatus(
                        url=peer_url,
                        online=False,
                        error=res["error"],
                    )
                return PeerStatus(
                    url=peer_url,
                    online=True,
                    latency_ms=latency,
                    node_id=res.get("node_id", "unknown"),
                    role=res.get("role", "unknown"),
                    running_tasks=res.get("running_tasks_count", 0),
                )
            else:
                return PeerStatus(
                    url=peer_url,
                    online=False,
                    error=resp.get("error", "Unknown RPC error"),
                )
        except Exception as exc:
            return PeerStatus(
                url=peer_url,
                online=False,
                error=str(exc),
            )

    def scan_peers(self, timeout: float = 3.0) -> Dict[str, PeerStatus]:
        """Scans all registered peers and returns health status table."""
        statuses: Dict[str, PeerStatus] = {}
        for p in self.config.peers:
            statuses[p] = self.check_peer_health(p, timeout=timeout)
        return statuses

    def dispatch_to_peer(
        self,
        peer_url: str,
        task_spec: str,
        task_id: Optional[str] = None,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """Dispatches an execution task to a specific remote peer."""
        client = SynapseRPCClient(target_url=peer_url)
        params = {
            "auth_token": self.config.auth_token,
            "task_spec": task_spec,
            "task_id": task_id or f"task_{int(time.time()*1000)}",
        }
        return client.call(method="dispatch_task", params=params, timeout=timeout)

    def dispatch_optimal(
        self,
        task_spec: str,
        task_id: Optional[str] = None,
        fallback_local: bool = True,
    ) -> Dict[str, Any]:
        """
        Dispatches a task to the healthiest online peer (lowest latency & task load).
        If no remote peer is reachable, falls back to local execution.
        """
        peer_statuses = self.scan_peers()
        online_peers = [s for s in peer_statuses.values() if s.online]

        if online_peers:
            # Sort by running tasks ascending, then latency ascending
            online_peers.sort(key=lambda p: (p.running_tasks, p.latency_ms))
            best_peer = online_peers[0]
            resp = self.dispatch_to_peer(best_peer.url, task_spec, task_id=task_id)
            if resp.get("ok"):
                return {
                    "dispatched_remote": True,
                    "peer_url": best_peer.url,
                    "peer_node_id": best_peer.node_id,
                    "result": resp.get("result"),
                }

        # Fallback local execution
        if fallback_local:
            from extensions.tasks.injector import EndToEndTaskInjector

            injector = EndToEndTaskInjector(vault_path=self.config.vault_path)
            res = injector.run_mamba_audit_task(task_spec=task_spec)
            return {
                "dispatched_remote": False,
                "peer_node_id": self.config.node_id,
                "result": {
                    "passed": res.passed,
                    "duration_sec": res.duration_sec,
                    "trajectory_hash": res.trajectory_hash,
                    "topology_mode": res.topology_mode,
                    "report_path": res.report_path,
                },
            }

        return {"ok": False, "error": "No healthy peer nodes available and fallback_local=False"}
