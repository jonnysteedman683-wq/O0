"""Unit tests for ADAS Dynamic Agent Topology Synthesizer and Execution Engine."""

from extensions.adas.topology import (
    ADASTopologySynthesizer,
    AgenticTopology,
    TopologyExecutionEngine,
)


def test_adas_mode_synthesis_classification():
    synthesizer = ADASTopologySynthesizer()

    # 1. Security / Audit -> Colosseum
    topo_sec = synthesizer.synthesize("Perform security audit and invariant fuzzing on Synapse RPC")
    assert topo_sec.mode == "adversarial_colosseum"
    assert "agent_red_probe" in topo_sec.nodes
    assert "agent_blue_shield" in topo_sec.nodes
    assert "agent_arbiter" in topo_sec.nodes

    # 2. Research / Literature -> Tree of Thought
    topo_res = synthesizer.synthesize("Research literature on state-space models and discover new architectures")
    assert topo_res.mode == "tree_of_thought_search"
    assert "agent_generator_a" in topo_res.nodes
    assert "agent_evaluator" in topo_res.nodes
    assert "agent_synthesizer" in topo_res.nodes

    # 3. Refactor / AST / Code -> Pipeline Assembly
    topo_code = synthesizer.synthesize("Refactor and optimize AST transformer to speed up execution benchmark")
    assert topo_code.mode == "pipeline_assembly"
    assert "agent_ast_parser" in topo_code.nodes
    assert "agent_transformer" in topo_code.nodes
    assert "agent_sandbox_runner" in topo_code.nodes

    # 4. General -> Consensus Ensemble
    topo_gen = synthesizer.synthesize("Decide on the best deployment schedule for next quarter")
    assert topo_gen.mode == "consensus_ensemble"
    assert "agent_specialist_1" in topo_gen.nodes
    assert "agent_consensus_judge" in topo_gen.nodes


def test_topology_graph_integrity():
    synthesizer = ADASTopologySynthesizer()

    for mode in ["adversarial_colosseum", "tree_of_thought_search", "pipeline_assembly", "consensus_ensemble"]:
        topo = synthesizer.synthesize("task", topology_mode=mode)
        # Verify all edges connect valid nodes
        for edge in topo.edges:
            assert edge.source_id in topo.nodes
            assert edge.target_id in topo.nodes
            assert bool(edge.message_type)

        # Verify execution order covers all nodes
        assert set(topo.execution_order) == set(topo.nodes.keys())


def test_topology_execution_engine_default():
    synthesizer = ADASTopologySynthesizer()
    engine = TopologyExecutionEngine()

    topo = synthesizer.synthesize("Audit Synapse security boundaries")
    result = engine.execute(topo, initial_input={"target_module": "synapse.net_bridge"})

    assert result["success"] is True
    assert result["mode"] == "adversarial_colosseum"
    assert "agent_arbiter" in result["node_outputs"]
    assert result["final_output"]["verdict"] == "CERTIFIED"
    assert result["trajectory_hash"].startswith("0x")
    assert len(result["edge_messages"]) >= 3


def test_topology_execution_with_custom_executors():
    synthesizer = ADASTopologySynthesizer()
    engine = TopologyExecutionEngine()

    topo = synthesizer.synthesize("Refactor code for performance", topology_mode="pipeline_assembly")

    custom_executors = {
        "agent_ast_parser": lambda inp, incoming: {"parsed_ast": "ast_ok", "node_count": 15},
        "agent_transformer": lambda inp, incoming: {"mutated_code": "def fast(): return 42"},
        "agent_sandbox_runner": lambda inp, incoming: {"status": "ALL_TESTS_PASS", "delta": +0.08},
    }

    result = engine.execute(topo, initial_input={"code": "def slow(): return 42"}, custom_executors=custom_executors)

    assert result["success"] is True
    assert result["final_output"]["status"] == "ALL_TESTS_PASS"
    assert result["final_output"]["delta"] == 0.08
    assert result["node_outputs"]["agent_ast_parser"]["node_count"] == 15
