"""Tests for SpatialVaultNavigator (extensions/spatial_memory/navigator.py)."""
from __future__ import annotations

from pathlib import Path

from extensions.spatial_memory import SpatialVaultNavigator


def test_spatial_vault_indexing_and_equidistant_routing(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    # 1. ML Station Core (Priority 10)
    (vault / "ML_STATION.md").write_text(
        "---\npriority: 10\nstation: ML\nquick_paths: [NN_TEST_BRIDGE, CORE_MAP]\ntags: [ml, neural_network]\n---\nML core knowledge.\n",
        encoding="utf-8",
    )

    # 2. Tests Station Core (Priority 10)
    (vault / "TESTS_STATION.md").write_text(
        "---\npriority: 10\nstation: TESTS\nquick_paths: [NN_TEST_BRIDGE, CORE_MAP]\ntags: [test, harness]\n---\nTesting harness.\n",
        encoding="utf-8",
    )

    # 3. Equidistant Midpoint Bridge (Priority 5) - connects ML and TESTS equally!
    (vault / "NN_TEST_BRIDGE.md").write_text(
        "---\npriority: 5\nstation: ML_TESTS\nquick_paths: [ML_STATION, TESTS_STATION]\ntags: [neural_network, test]\n---\nNeural Network verification test.\n",
        encoding="utf-8",
    )

    # 4. Low priority background research note (Priority 2)
    (vault / "RANDOM_PAPER.md").write_text(
        "---\npriority: 2\nstation: ML\nquick_paths: []\ntags: [neural_network, trivia]\n---\nPeripheral background data.\n",
        encoding="utf-8",
    )

    navigator = SpatialVaultNavigator(vault)
    stats = navigator.index_vault()
    assert stats["indexed"] == 4
    assert stats["stations"] >= 2

    # Check Station Cores
    ml_core = navigator.get_station_core("ML")
    assert ml_core is not None
    assert ml_core.priority == 10

    test_core = navigator.get_station_core("TESTS")
    assert test_core is not None
    assert test_core.priority == 10

    # Verify Equidistant Midpoint:
    # Distance from ML_STATION to NN_TEST_BRIDGE is exactly 1 hop
    path_from_ml = navigator.route_quick_path("ML_STATION", "NN_TEST_BRIDGE")
    assert path_from_ml == ["ML_STATION", "NN_TEST_BRIDGE"]
    assert len(path_from_ml) - 1 == 1

    # Distance from TESTS_STATION to NN_TEST_BRIDGE is also exactly 1 hop (equal traversal time)
    path_from_test = navigator.route_quick_path("TESTS_STATION", "NN_TEST_BRIDGE")
    assert path_from_test == ["TESTS_STATION", "NN_TEST_BRIDGE"]
    assert len(path_from_test) - 1 == 1

    # Priority-filtered retrieval: P10 and P5 retrieved; P2 ignored when min_priority=5
    results = navigator.priority_search(keywords=["neural_network"], min_priority=5)
    names = [r.name for r in results]
    assert "ML_STATION" in names
    assert "NN_TEST_BRIDGE" in names
    assert "RANDOM_PAPER" not in names  # Filtered out by priority gradient!


def test_live_o0_directory_topology():
    """Verify live O0-DIRECTORY vault topology, cores, and equidistant bridges."""
    navigator = SpatialVaultNavigator()
    stats = navigator.index_vault()

    # Must find all our created stations and nodes
    assert stats["indexed"] >= 10
    assert stats["stations"] >= 4

    # 1. Verify Core Stations exist at Priority 10
    ml_core = navigator.get_station_core("ML")
    assert ml_core is not None
    assert ml_core.priority == 10

    tests_core = navigator.get_station_core("TESTS")
    assert tests_core is not None
    assert tests_core.priority == 10

    reasoning_core = navigator.get_station_core("REASONING")
    assert reasoning_core is not None
    assert reasoning_core.priority == 10

    systems_core = navigator.get_station_core("SYSTEMS")
    assert systems_core is not None
    assert systems_core.priority == 10

    # 2. Verify Equidistant Midpoint Bridge: NEURAL_NETWORK_TESTS (P5)
    nn_bridge = navigator.nodes.get("NEURAL_NETWORK_TESTS")
    assert nn_bridge is not None
    assert nn_bridge.priority == 5

    # 1 hop from ML_STATION_MAP
    route_from_ml = navigator.route_quick_path("ML_STATION_MAP", "NEURAL_NETWORK_TESTS")
    assert route_from_ml == ["ML_STATION_MAP", "NEURAL_NETWORK_TESTS"]

    # 1 hop from TESTS_STATION_MAP
    route_from_tests = navigator.route_quick_path("TESTS_STATION_MAP", "NEURAL_NETWORK_TESTS")
    assert route_from_tests == ["TESTS_STATION_MAP", "NEURAL_NETWORK_TESTS"]

    # 2-hop traversal between stations via bridge
    route_ml_to_tests = navigator.route_quick_path("ML_STATION_MAP", "TESTS_STATION_MAP")
    assert len(route_ml_to_tests) <= 3

