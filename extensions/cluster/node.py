"""
Cluster Node Daemon for O0 Multi-Computer Execution.
Hosts the RPC service, authenticates remote peers, and executes distributed tasks.
"""

from __future__ import annotations

import os
import platform
import socket
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from extensions.cluster.config import ClusterConfig
from extensions.spatial_memory import SpatialVaultNavigator
from extensions.synapse.net_bridge import SynapseRPCServer


class ClusterNode:
    """Represents a running cluster node daemon on a local machine."""

    def __init__(self, config: Optional[ClusterConfig] = None):
        self.config = config or ClusterConfig.load()
        self.start_time = time.time()
        self.running_tasks: Dict[str, Any] = {}
        self.completed_tasks: List[Dict[str, Any]] = []

        self.server = SynapseRPCServer(
            host=self.config.listen_host,
            port=self.config.listen_port,
        )
        self.navigator = SpatialVaultNavigator(self.config.vault_path) if self.config.vault_path else SpatialVaultNavigator()

        # Register RPC endpoints
        self.server.register_method("ping", self._handle_ping)
        self.server.register_method("dispatch_task", self._handle_dispatch_task)
        self.server.register_method("query_status", self._handle_query_status)
        self.server.register_method("query_spatial_memory", self._handle_query_spatial_memory)

    def _verify_auth(self, params: Dict[str, Any]) -> bool:
        """Verifies shared cluster secret token."""
        token = params.get("auth_token", "")
        return token == self.config.auth_token

    def _handle_ping(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Liveness check and system metadata."""
        if not self._verify_auth(params):
            return {"error": "Unauthorized: invalid auth_token"}

        uptime_sec = round(time.time() - self.start_time, 2)
        return {
            "node_id": self.config.node_id,
            "role": self.config.role,
            "status": "ONLINE",
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python_version": sys.version.split()[0],
            "uptime_sec": uptime_sec,
            "peers_registered": len(self.config.peers),
            "running_tasks_count": len(self.running_tasks),
        }

    def _handle_dispatch_task(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Executes an injected task received from another computer."""
        if not self._verify_auth(params):
            return {"error": "Unauthorized: invalid auth_token"}

        task_id = params.get("task_id", f"task_{int(time.time()*1000)}")
        task_spec = params.get("task_spec", "")
        if not task_spec:
            return {"error": "Empty task_spec"}

        t_start = time.perf_counter()
        self.running_tasks[task_id] = {"task_spec": task_spec, "started_at": time.time()}

        try:
            # Lazy import to avoid circular dependency
            from extensions.tasks.injector import EndToEndTaskInjector

            injector = EndToEndTaskInjector(vault_path=self.config.vault_path)
            res = injector.run_mamba_audit_task(task_spec=task_spec)

            exec_record = {
                "task_id": task_id,
                "node_id": self.config.node_id,
                "passed": res.passed,
                "duration_sec": res.duration_sec,
                "trajectory_hash": res.trajectory_hash,
                "topology_mode": res.topology_mode,
                "report_path": res.report_path,
                "personal_note": res.personal_note,
            }
        except Exception as e:
            exec_record = {
                "task_id": task_id,
                "node_id": self.config.node_id,
                "passed": False,
                "duration_sec": round(time.perf_counter() - t_start, 4),
                "error": str(e),
            }
        finally:
            self.running_tasks.pop(task_id, None)
            self.completed_tasks.append(exec_record)

        return exec_record

    def _handle_query_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Provides in-depth telemetry on tasks and execution metrics."""
        if not self._verify_auth(params):
            return {"error": "Unauthorized: invalid auth_token"}

        return {
            "node_id": self.config.node_id,
            "role": self.config.role,
            "completed_tasks_count": len(self.completed_tasks),
            "recent_tasks": self.completed_tasks[-5:],
            "active_tasks": list(self.running_tasks.values()),
        }

    def _handle_query_spatial_memory(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Allows remote cluster nodes to query this node's spatial memory vault."""
        if not self._verify_auth(params):
            return {"error": "Unauthorized: invalid auth_token"}

        keywords = params.get("keywords", [])
        min_priority = int(params.get("min_priority", 5))
        station = params.get("station")

        self.navigator.index_vault()
        nodes = self.navigator.priority_search(
            keywords=keywords,
            min_priority=min_priority,
            target_station=station,
            limit=params.get("limit", 5),
        )

        return {
            "query_keywords": keywords,
            "matches_count": len(nodes),
            "nodes": [
                {
                    "name": n.name,
                    "station": n.station,
                    "priority": n.priority,
                    "quick_paths": n.quick_paths,
                    "path": n.path,
                }
                for n in nodes
            ],
        }

    def start(self) -> None:
        """Starts node RPC server."""
        self.server.start()

    def stop(self) -> None:
        """Gracefully shuts down node RPC server."""
        self.server.stop()
