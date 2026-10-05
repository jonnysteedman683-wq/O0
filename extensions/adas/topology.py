"""
ADAS: Automated Design of Agentic Systems Engine for O0.
Adapted from HORIZONTAL's ADAS paradigm (Shengran Hu et al., ICLR 2025).

Dynamically synthesizes and executes specialized multi-agent communication topologies
tailored to task intent:
- Adversarial Colosseum: Red probe vs Blue shield arbitrated by Invariant Judge.
- Tree of Thought Search: Divergent hypothesis generators, Critic, and Solution Synthesizer.
- Pipeline Assembly: AST Analyzer, Mutator, and Isolated Sandbox Verifier.
- Consensus Ensemble: Diverse specialist solvers with Byzantine Fault Tolerant (BFT) Quorum.
"""

from __future__ import annotations

import collections
import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class AgentNode:
    id: str
    role_type: str  # "adversary", "defender", "judge", "divergent", "critic", "convergent", "analyzer", "mutator", "verifier", "solver", "voter"
    focus: str
    system_prompt: str
    capabilities: List[str] = field(default_factory=list)


@dataclass
class CommunicationEdge:
    source_id: str
    target_id: str
    message_type: str  # e.g., "challenge", "defense_proof", "verdict_feedback", "branch", "pruned_branches", "ast_graph", "candidate_binary", "vote"


@dataclass
class AgenticTopology:
    mode: str  # "adversarial_colosseum", "tree_of_thought_search", "pipeline_assembly", "consensus_ensemble"
    task_spec: str
    nodes: Dict[str, AgentNode]
    edges: List[CommunicationEdge]
    execution_order: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_node(self, node_id: str) -> Optional[AgentNode]:
        return self.nodes.get(node_id)

    def get_outgoing_edges(self, node_id: str) -> List[CommunicationEdge]:
        return [e for e in self.edges if e.source_id == node_id]

    def get_incoming_edges(self, node_id: str) -> List[CommunicationEdge]:
        return [e for e in self.edges if e.target_id == node_id]


class ADASTopologySynthesizer:
    """Synthesizes dynamic multi-agent topologies from natural language task intent."""

    def synthesize(self, task_spec: str, topology_mode: str = "auto") -> AgenticTopology:
        if not task_spec or not task_spec.strip():
            task_spec = "general_assistance"

        lower_task = task_spec.lower()

        if topology_mode == "auto":
            if any(w in lower_task for w in ["security", "audit", "exploit", "leak", "vulnerability", "invariant", "fuzz"]):
                mode = "adversarial_colosseum"
            elif any(w in lower_task for w in ["research", "literature", "explore", "survey", "gather", "brainstorm", "discover"]):
                mode = "tree_of_thought_search"
            elif any(w in lower_task for w in ["refactor", "compile", "optimize", "speed", "benchmark", "transform", "ast", "code"]):
                mode = "pipeline_assembly"
            else:
                mode = "consensus_ensemble"
        else:
            mode = topology_mode

        if mode == "adversarial_colosseum":
            return self._build_colosseum(task_spec)
        elif mode == "tree_of_thought_search":
            return self._build_tree_of_thought(task_spec)
        elif mode == "pipeline_assembly":
            return self._build_pipeline_assembly(task_spec)
        else:
            return self._build_consensus_ensemble(task_spec)

    def _build_colosseum(self, task_spec: str) -> AgenticTopology:
        nodes = {
            "agent_red_probe": AgentNode(
                id="agent_red_probe",
                role_type="adversary",
                focus="injection_and_fuzzing",
                system_prompt="Analyze code/system to discover boundary weaknesses, edge cases, and exploit vectors.",
                capabilities=["fuzzing", "edge_case_generation", "stress_test"],
            ),
            "agent_blue_shield": AgentNode(
                id="agent_blue_shield",
                role_type="defender",
                focus="boundary_verification_and_hardening",
                system_prompt="Defend against probed weaknesses by providing invariant proofs and hardening patches.",
                capabilities=["invariant_guard", "hardening", "proof_construction"],
            ),
            "agent_arbiter": AgentNode(
                id="agent_arbiter",
                role_type="judge",
                focus="invariant_certification",
                system_prompt="Verify red probes against blue defenses to deliver final certification and verdict.",
                capabilities=["bft_arbitration", "verdict_certification"],
            ),
        }
        edges = [
            CommunicationEdge("agent_red_probe", "agent_blue_shield", "challenge"),
            CommunicationEdge("agent_blue_shield", "agent_arbiter", "defense_proof"),
            CommunicationEdge("agent_arbiter", "agent_red_probe", "verdict_feedback"),
        ]
        execution_order = ["agent_red_probe", "agent_blue_shield", "agent_arbiter"]
        return AgenticTopology(
            mode="adversarial_colosseum",
            task_spec=task_spec,
            nodes=nodes,
            edges=edges,
            execution_order=execution_order,
            metadata={"resilience_tier": "adversarial_verified"},
        )

    def _build_tree_of_thought(self, task_spec: str) -> AgenticTopology:
        nodes = {
            "agent_generator_a": AgentNode(
                id="agent_generator_a",
                role_type="divergent",
                focus="hypothesis_breadth",
                system_prompt="Generate diverse, broad hypotheses and conceptual angles for the problem space.",
                capabilities=["broad_search", "divergent_ideation"],
            ),
            "agent_generator_b": AgentNode(
                id="agent_generator_b",
                role_type="divergent",
                focus="hypothesis_depth",
                system_prompt="Generate deep, domain-specific technical avenues and specialized solutions.",
                capabilities=["deep_search", "technical_specialization"],
            ),
            "agent_evaluator": AgentNode(
                id="agent_evaluator",
                role_type="critic",
                focus="empirical_scoring",
                system_prompt="Critique and empirically score all branches, pruning suboptimal trajectories.",
                capabilities=["heuristic_scoring", "branch_pruning"],
            ),
            "agent_synthesizer": AgentNode(
                id="agent_synthesizer",
                role_type="convergent",
                focus="solution_crystallization",
                system_prompt="Crystallize winning pruned branches into an actionable, unified synthesis.",
                capabilities=["synthesis", "plan_generation"],
            ),
        }
        edges = [
            CommunicationEdge("agent_generator_a", "agent_evaluator", "branch_a"),
            CommunicationEdge("agent_generator_b", "agent_evaluator", "branch_b"),
            CommunicationEdge("agent_evaluator", "agent_synthesizer", "pruned_branches"),
        ]
        execution_order = ["agent_generator_a", "agent_generator_b", "agent_evaluator", "agent_synthesizer"]
        return AgenticTopology(
            mode="tree_of_thought_search",
            task_spec=task_spec,
            nodes=nodes,
            edges=edges,
            execution_order=execution_order,
            metadata={"search_type": "mcts_branching"},
        )

    def _build_pipeline_assembly(self, task_spec: str) -> AgenticTopology:
        nodes = {
            "agent_ast_parser": AgentNode(
                id="agent_ast_parser",
                role_type="analyzer",
                focus="syntax_inspection",
                system_prompt="Parse source input into AST graphs, checking complexity metrics and syntax integrity.",
                capabilities=["ast_parsing", "cyclomatic_check"],
            ),
            "agent_transformer": AgentNode(
                id="agent_transformer",
                role_type="mutator",
                focus="code_transmutation",
                system_prompt="Apply target code mutations, optimizations, and refactoring on AST structures.",
                capabilities=["ast_mutation", "optimization", "refactor"],
            ),
            "agent_sandbox_runner": AgentNode(
                id="agent_sandbox_runner",
                role_type="verifier",
                focus="test_execution",
                system_prompt="Execute mutated code candidates in isolated deterministic sandboxes.",
                capabilities=["sandbox_execution", "regression_verification"],
            ),
        }
        edges = [
            CommunicationEdge("agent_ast_parser", "agent_transformer", "ast_graph"),
            CommunicationEdge("agent_transformer", "agent_sandbox_runner", "candidate_binary"),
        ]
        execution_order = ["agent_ast_parser", "agent_transformer", "agent_sandbox_runner"]
        return AgenticTopology(
            mode="pipeline_assembly",
            task_spec=task_spec,
            nodes=nodes,
            edges=edges,
            execution_order=execution_order,
            metadata={"execution_pipeline": "sequential_dag"},
        )

    def _build_consensus_ensemble(self, task_spec: str) -> AgenticTopology:
        nodes = {
            "agent_specialist_1": AgentNode(
                id="agent_specialist_1",
                role_type="solver",
                focus="primary_solution",
                system_prompt="Develop primary direct solution proposal.",
                capabilities=["direct_solving"],
            ),
            "agent_specialist_2": AgentNode(
                id="agent_specialist_2",
                role_type="solver",
                focus="alternative_solution",
                system_prompt="Develop orthogonal, creative alternative solution proposal.",
                capabilities=["alternative_solving"],
            ),
            "agent_consensus_judge": AgentNode(
                id="agent_consensus_judge",
                role_type="voter",
                focus="bft_quorum",
                system_prompt="Weigh competing proposals, reconcile trade-offs, and cast final consensus vote.",
                capabilities=["bft_consensus", "tradeoff_arbitration"],
            ),
        }
        edges = [
            CommunicationEdge("agent_specialist_1", "agent_consensus_judge", "vote_1"),
            CommunicationEdge("agent_specialist_2", "agent_consensus_judge", "vote_2"),
        ]
        execution_order = ["agent_specialist_1", "agent_specialist_2", "agent_consensus_judge"]
        return AgenticTopology(
            mode="consensus_ensemble",
            task_spec=task_spec,
            nodes=nodes,
            edges=edges,
            execution_order=execution_order,
            metadata={"consensus_model": "bft_quorum"},
        )


class TopologyExecutionEngine:
    """Executes an AgenticTopology passing structured messages along communication channels."""

    def execute(
        self,
        topology: AgenticTopology,
        initial_input: Any,
        custom_executors: Optional[Dict[str, Callable[[Any, Dict[str, Any]], Any]]] = None,
    ) -> Dict[str, Any]:
        custom_executors = custom_executors or {}
        node_outputs: Dict[str, Any] = {}
        edge_messages: List[Dict[str, Any]] = []

        for node_id in topology.execution_order:
            node = topology.get_node(node_id)
            if not node:
                continue

            # Gather incoming messages from upstream nodes
            incoming_edges = topology.get_incoming_edges(node_id)
            incoming_data = {}
            for edge in incoming_edges:
                if edge.source_id in node_outputs:
                    incoming_data[edge.message_type] = node_outputs[edge.source_id]

            # Context provided to the agent
            agent_input = incoming_data if incoming_data else initial_input

            # Execute via custom callable if registered, or simulated deterministic runner
            if node_id in custom_executors:
                output = custom_executors[node_id](agent_input, incoming_data)
            else:
                output = self._default_node_runner(node, topology.mode, agent_input)

            node_outputs[node_id] = output

            # Record outgoing edge transmissions
            for edge in topology.get_outgoing_edges(node_id):
                edge_messages.append({
                    "from": edge.source_id,
                    "to": edge.target_id,
                    "message_type": edge.message_type,
                    "payload_preview": str(output)[:100],
                })

        # Determine final synthesized result (typically the last node in execution order)
        final_node_id = topology.execution_order[-1]
        final_output = node_outputs.get(final_node_id)

        # Compute deterministic Merkle/SHA-256 fingerprint of the execution trajectory
        fingerprint_src = f"{topology.mode}:{list(node_outputs.keys())}:{final_output}"
        traj_hash = hashlib.sha256(fingerprint_src.encode("utf-8")).hexdigest()[:16]

        return {
            "mode": topology.mode,
            "task_spec": topology.task_spec,
            "final_output": final_output,
            "node_outputs": node_outputs,
            "edge_messages": edge_messages,
            "trajectory_hash": f"0x{traj_hash}",
            "success": True,
        }

    def _default_node_runner(self, node: AgentNode, mode: str, agent_input: Any) -> Any:
        """Deterministic default runner simulating agent execution for testing and fallbacks."""
        if node.role_type == "adversary":
            return {"challenge": "Boundary edge case identified: potential integer overflow / empty buffer", "target": agent_input}
        elif node.role_type == "defender":
            return {"proof": "Invariance established with bounds clamping [0, 1000]", "challenge_handled": agent_input}
        elif node.role_type == "judge":
            return {"verdict": "CERTIFIED", "confidence": 0.98, "reasoning": "Defender satisfactorily addressed all edge cases"}
        elif node.role_type == "divergent":
            return {"hypothesis": f"Exploration branch for {node.id}", "input": agent_input}
        elif node.role_type == "critic":
            return {"ranked_branches": ["branch_b", "branch_a"], "pruning_threshold": 0.75}
        elif node.role_type == "convergent":
            return {"synthesis": "Unified crystallized solution combining top hypothesis with empirical bounds"}
        elif node.role_type == "analyzer":
            return {"ast_valid": True, "node_count": 42, "cyclomatic_complexity": 3}
        elif node.role_type == "mutator":
            return {"mutation": "Injected memoization and dead-code elimination", "source": agent_input}
        elif node.role_type == "verifier":
            return {"test_passed": True, "coverage": 100.0, "latency_ms": 1.2}
        elif node.role_type == "solver":
            return {"proposal": f"Solution from {node.id}", "confidence": 0.9}
        elif node.role_type == "voter":
            return {"consensus": "Proposal adopted with 2/2 unanimous quorum", "verdict": "ACCEPTED"}
        return {"result": f"Executed {node.id}", "input": agent_input}
