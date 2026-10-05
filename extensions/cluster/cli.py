"""
Command-Line Interface for O0 Multi-Computer Cluster Management.
Usage:
    python -m extensions.cluster.cli start [--host 0.0.0.0] [--port 8990] [--node-id NAME] [--role WORKER]
    python -m extensions.cluster.cli status
    python -m extensions.cluster.cli dispatch --task "..." [--peer http://<ip>:8990]
    python -m extensions.cluster.cli init-config
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from extensions.cluster.config import ClusterConfig
from extensions.cluster.mesh import ClusterMesh
from extensions.cluster.node import ClusterNode


def cmd_init_config(args: argparse.Namespace) -> None:
    config = ClusterConfig()
    path = config.save("cluster_config.json")
    print(f"✅ Initialized cluster config template at: {path.resolve()}")
    print("Edit 'cluster_config.json' to specify your node_id, peers, and auth_token.")


def cmd_start(args: argparse.Namespace) -> None:
    config = ClusterConfig.load()
    if args.host:
        config.listen_host = args.host
    if args.port:
        config.listen_port = args.port
    if args.node_id:
        config.node_id = args.node_id
    if args.role:
        config.role = args.role.upper()

    node = ClusterNode(config)
    print(f"🚀 Starting O0 Cluster Node [{config.node_id}] ({config.role}) on http://{config.listen_host}:{config.listen_port}")
    print(f"   Auth Token: {config.auth_token[:4]}****")
    print(f"   Registered Peers: {len(config.peers)}")
    print("Press Ctrl+C to stop node daemon.")
    node.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Stopping cluster node...")
        node.stop()
        print("Node stopped cleanly.")


def cmd_status(args: argparse.Namespace) -> None:
    config = ClusterConfig.load()
    mesh = ClusterMesh(config)
    print(f"📍 Local Node: {config.node_id} (Role: {config.role})")
    print(f"   Endpoint: http://{config.listen_host}:{config.listen_port}")
    print("-" * 75)
    print(f"{'PEER URL':<35} {'STATUS':<10} {'LATENCY':<12} {'NODE ID':<15}")
    print("-" * 75)

    if not config.peers:
        print("  (No peers configured in cluster_config.json. Add peer URLs to start clustering!)")
    else:
        statuses = mesh.scan_peers()
        for url, st in statuses.items():
            status_str = "🟢 ONLINE" if st.online else "🔴 OFFLINE"
            lat_str = f"{st.latency_ms} ms" if st.online else "N/A"
            print(f"{url:<35} {status_str:<10} {lat_str:<12} {st.node_id:<15}")
    print("-" * 75)


def cmd_dispatch(args: argparse.Namespace) -> None:
    config = ClusterConfig.load()
    mesh = ClusterMesh(config)
    print(f"📤 Dispatching task: '{args.task}'")

    if args.peer:
        print(f"Targeting peer: {args.peer}")
        res = mesh.dispatch_to_peer(args.peer, args.task)
    else:
        print("Auto-routing to optimal available peer...")
        res = mesh.dispatch_optimal(args.task)

    print("\nResult received:")
    print(json.dumps(res, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="O0 Multi-Computer Cluster Manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init-config
    subparsers.add_parser("init-config", help="Create sample cluster_config.json")

    # start
    p_start = subparsers.add_parser("start", help="Start the local cluster node daemon")
    p_start.add_argument("--host", type=str, default=None, help="Host address to bind")
    p_start.add_argument("--port", type=int, default=None, help="Port to listen on")
    p_start.add_argument("--node-id", type=str, default=None, help="Unique node identifier")
    p_start.add_argument("--role", type=str, default=None, help="Node role (PRIMARY/WORKER/HYBRID)")

    # status
    subparsers.add_parser("status", help="Check status of cluster peers")

    # dispatch
    p_disp = subparsers.add_parser("dispatch", help="Dispatch a task across the cluster")
    p_disp.add_argument("--task", type=str, required=True, help="Task description to execute")
    p_disp.add_argument("--peer", type=str, default=None, help="Specific peer URL to target")

    args = parser.parse_args()
    if args.command == "init-config":
        cmd_init_config(args)
    elif args.command == "start":
        cmd_start(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "dispatch":
        cmd_dispatch(args)


if __name__ == "__main__":
    main()
