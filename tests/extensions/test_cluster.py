"""Unit tests for O0 Multi-Computer Cluster Architecture."""

import shutil
import time
from pathlib import Path

from extensions.cluster.config import ClusterConfig
from extensions.cluster.mesh import ClusterMesh
from extensions.cluster.node import ClusterNode
from extensions.spatial_memory.navigator import REPO_VAULT_PATH


def test_cluster_config_load_and_save(tmp_path: Path):
    cfg_file = tmp_path / "test_cluster_config.json"
    cfg = ClusterConfig(
        node_id="test_worker_1",
        role="WORKER",
        listen_host="127.0.0.1",
        listen_port=8991,
        auth_token="secret-123",
        peers=["http://127.0.0.1:8992"],
    )
    saved_path = cfg.save(cfg_file)
    assert saved_path.exists()

    loaded = ClusterConfig.load(cfg_file)
    assert loaded.node_id == "test_worker_1"
    assert loaded.role == "WORKER"
    assert loaded.listen_port == 8991
    assert loaded.auth_token == "secret-123"
    assert loaded.peers == ["http://127.0.0.1:8992"]


def test_cluster_node_daemon_ping_and_auth():
    config = ClusterConfig(
        node_id="node_alpha",
        role="PRIMARY",
        listen_host="127.0.0.1",
        listen_port=8993,
        auth_token="auth-pass-xyz",
    )
    node = ClusterNode(config)
    node.start()
    time.sleep(0.1)

    mesh = ClusterMesh(config)

    try:
        # 1. Healthy ping with correct auth token
        status = mesh.check_peer_health("http://127.0.0.1:8993")
        assert status.online is True
        assert status.node_id == "node_alpha"
        assert status.role == "PRIMARY"
        assert status.latency_ms >= 0.0

        # 2. Ping with incorrect auth token rejected
        bad_config = ClusterConfig(auth_token="wrong-token")
        bad_mesh = ClusterMesh(bad_config)
        bad_status = bad_mesh.check_peer_health("http://127.0.0.1:8993")
        assert bad_status.online is False
        assert "Unauthorized" in str(bad_status.error)
    finally:
        node.stop()


def test_cluster_mesh_dispatch_and_fallback(tmp_path: Path):
    # Local fallback writes a task report into the vault; use a copy so the real
    # O0-DIRECTORY is never touched by a test run.
    vault = tmp_path / "vault"
    shutil.copytree(REPO_VAULT_PATH, vault, ignore=shutil.ignore_patterns("REPORTS", ".obsidian"))
    config = ClusterConfig(
        vault_path=str(vault),
        node_id="standalone_node",
        role="HYBRID",
        listen_host="127.0.0.1",
        listen_port=8994,
        auth_token="token-local",
        peers=[],  # No remote peers
    )
    mesh = ClusterMesh(config)

    # When no remote peers exist, dispatch_optimal falls back to local execution
    res = mesh.dispatch_optimal("Verify Mamba SSM stability on standalone node")
    assert res["dispatched_remote"] is False
    assert res["peer_node_id"] == "standalone_node"
    assert res["result"]["passed"] is True
    assert Path(res["result"]["report_path"]).is_relative_to(vault)
