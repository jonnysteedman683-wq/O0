"""
MCTS: Monte Carlo Tree Search Dynamic Pipeline DAG Synthesizer for O0.
Adapted from HORIZONTAL's production MCTS synthesizer.

Autonomously searches the combinatorial space of tools and subroutines to assemble,
wire, and execute optimal multi-stage DAG pipelines for natural language goals:
1. Tool Capability Catalog: Auto-indexes tools, functions, signatures, and capabilities.
2. MCTS Search Engine: Selection (UCT), Expansion, Simulation, and Backpropagation.
3. Auto-DAG Data Bus Wiring: Dynamically binds $input and $stages.<stage_id>.result.
4. Pipeline DAG Executor: Resolves dependencies and executes the verified DAG with Merkle provenance.
"""

from __future__ import annotations

import hashlib
import inspect
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple


@dataclass
class ToolDescriptor:
    name: str
    docstring: str
    entry_fn: Callable[..., Any]
    param_names: List[str]
    capabilities: List[str] = field(default_factory=list)

    def match_score(self, goal_tokens: Set[str]) -> float:
        """Computes semantic overlap score between tool and goal tokens."""
        text = f"{self.name} {self.docstring} {' '.join(self.capabilities)}".lower()
        score = 0.0
        for tok in goal_tokens:
            if tok in text:
                score += 1.0
        return score


@dataclass
class PipelineStage:
    stage_id: str
    tool_name: str
    tool_fn: Callable[..., Any]
    inputs: Dict[str, Any]  # e.g., {"text": "$input.raw_text", "clean": "$stages.stage_1.result"}
    depends_on: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class PipelineDAG:
    pipeline_id: str
    goal: str
    stages: List[PipelineStage]
    execution_order: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)


class MCTSNode:
    """Node in the Monte Carlo Search Tree representing a partial tool sequence."""

    def __init__(self, sequence: List[ToolDescriptor], parent: Optional[MCTSNode] = None):
        self.sequence = sequence
        self.parent = parent
        self.children: List[MCTSNode] = []
        self.visits = 0
        self.total_reward = 0.0
        self.best_reward = 0.0

    def uct_score(self, exploration_constant: float = 1.414) -> float:
        if self.visits == 0:
            return float("inf")
        exploitation = self.total_reward / self.visits
        parent_visits = self.parent.visits if self.parent and self.parent.visits > 0 else 1
        exploration = exploration_constant * math.sqrt(math.log(parent_visits) / self.visits)
        return exploitation + exploration

    def is_fully_expanded(self, catalog_size: int, max_depth: int) -> bool:
        if len(self.sequence) >= max_depth:
            return True
        return len(self.children) >= (catalog_size - len(self.sequence))


class MCTSPipelineSynthesizer:
    """Monte Carlo Tree Search dynamic pipeline DAG synthesizer."""

    def __init__(self, exploration_constant: float = 1.414, max_depth: int = 4):
        self.exploration_constant = exploration_constant
        self.max_depth = max_depth
        self.catalog: Dict[str, ToolDescriptor] = {}

    def register_tool(
        self,
        name: str,
        entry_fn: Callable[..., Any],
        docstring: str = "",
        capabilities: Optional[List[str]] = None,
    ) -> None:
        """Registers a callable tool into the synthesizer catalog."""
        doc = docstring or entry_fn.__doc__ or name
        sig = inspect.signature(entry_fn)
        params = list(sig.parameters.keys())
        caps = capabilities or [name.lower()]

        self.catalog[name] = ToolDescriptor(
            name=name,
            docstring=doc.strip(),
            entry_fn=entry_fn,
            param_names=params,
            capabilities=caps,
        )

    def search_optimal_pipeline(
        self,
        goal: str,
        simulations: int = 40,
    ) -> PipelineDAG:
        """
        Executes MCTS (Selection, Expansion, Simulation, Backprop) to discover
        the optimal tool sequence and auto-wires a PipelineDAG.
        """
        if not self.catalog:
            raise ValueError("No tools registered in catalog")

        goal_tokens = {w.lower() for w in goal.split() if len(w) > 2}
        available_tools = list(self.catalog.values())

        root = MCTSNode(sequence=[])
        best_overall_node: Optional[MCTSNode] = None
        best_overall_score: float = -1.0

        for _ in range(simulations):
            # 1. Selection
            node = root
            while node.children and node.is_fully_expanded(len(available_tools), self.max_depth):
                node = max(node.children, key=lambda c: c.uct_score(self.exploration_constant))

            # 2. Expansion
            used_names = {t.name for t in node.sequence}
            candidates = [t for t in available_tools if t.name not in used_names]
            if candidates and len(node.sequence) < self.max_depth:
                existing_child_tools = {c.sequence[-1].name for c in node.children}
                unexpanded = [c for c in candidates if c.name not in existing_child_tools]
                if unexpanded:
                    tool_to_add = random.choice(unexpanded)
                    new_node = MCTSNode(sequence=node.sequence + [tool_to_add], parent=node)
                    node.children.append(new_node)
                    node = new_node

            # 3. Simulation (Rollout Evaluation)
            reward = self._evaluate_sequence(node.sequence, goal_tokens)

            if reward > best_overall_score and len(node.sequence) >= 1:
                best_overall_score = reward
                best_overall_node = node

            # 4. Backpropagation
            curr: Optional[MCTSNode] = node
            while curr is not None:
                curr.visits += 1
                curr.total_reward += reward
                if reward > curr.best_reward:
                    curr.best_reward = reward
                curr = curr.parent

        if best_overall_node and best_overall_node.sequence:
            best_sequence = best_overall_node.sequence
        elif root.children:
            best_sequence = max(root.children, key=lambda c: c.total_reward / max(1, c.visits)).sequence
        else:
            best_sequence = [max(available_tools, key=lambda t: t.match_score(goal_tokens))]

        return self._wire_pipeline_dag(goal, best_sequence)

    def _evaluate_sequence(self, sequence: List[ToolDescriptor], goal_tokens: Set[str]) -> float:
        """Evaluates pipeline fitness based on semantic coverage, length penalization, and diversity."""
        if not sequence:
            return 0.0

        total_match = sum(t.match_score(goal_tokens) for t in sequence)
        covered_tokens = set()
        for t in sequence:
            text = f"{t.name} {t.docstring} {' '.join(t.capabilities)}".lower()
            covered_tokens.update(tok for tok in goal_tokens if tok in text)

        coverage_ratio = len(covered_tokens) / max(1, len(goal_tokens))
        # Optimal pipeline length bonus (2-3 tools)
        length_penalty = 0.05 * abs(len(sequence) - 2.5)

        reward = (0.6 * coverage_ratio) + (0.3 * (total_match / (len(sequence) * 3 + 1))) - length_penalty
        return max(0.01, round(reward, 4))

    def _wire_pipeline_dag(self, goal: str, sequence: List[ToolDescriptor]) -> PipelineDAG:
        """Auto-wires data bindings and dependency injection across pipeline stages."""
        stages: List[PipelineStage] = []
        execution_order: List[str] = []

        for i, tool in enumerate(sequence):
            stage_id = f"stage_{i+1}_{tool.name}"
            execution_order.append(stage_id)

            inputs: Dict[str, Any] = {}
            depends_on: List[str] = []

            if i == 0:
                # First stage binds to initial payload
                for param in tool.param_names:
                    inputs[param] = f"$input.{param}"
            else:
                prev_stage = stages[i - 1]
                depends_on.append(prev_stage.stage_id)
                # Primary param takes output from preceding stage
                if tool.param_names:
                    primary_param = tool.param_names[0]
                    inputs[primary_param] = f"$stages.{prev_stage.stage_id}.result"
                    for extra_param in tool.param_names[1:]:
                        inputs[extra_param] = f"$input.{extra_param}"

            stages.append(
                PipelineStage(
                    stage_id=stage_id,
                    tool_name=tool.name,
                    tool_fn=tool.entry_fn,
                    inputs=inputs,
                    depends_on=depends_on,
                    description=tool.docstring,
                )
            )

        pipeline_hash = hashlib.sha256(f"{goal}:{[s.stage_id for s in stages]}".encode("utf-8")).hexdigest()[:12]
        return PipelineDAG(
            pipeline_id=f"dag_{pipeline_hash}",
            goal=goal,
            stages=stages,
            execution_order=execution_order,
            metadata={"mcts_depth": len(sequence)},
        )


class PipelineExecutor:
    """Executes a PipelineDAG resolving data bindings and computing Merkle root hashes."""

    def execute(self, dag: PipelineDAG, initial_input: Dict[str, Any]) -> Dict[str, Any]:
        stage_results: Dict[str, Any] = {}
        stage_telemetry: List[Dict[str, Any]] = []
        t_start = time.perf_counter()

        for stage_id in dag.execution_order:
            stage = next(s for s in dag.stages if s.stage_id == stage_id)
            resolved_kwargs: Dict[str, Any] = {}

            # Resolve inputs
            for param, binding in stage.inputs.items():
                if isinstance(binding, str) and binding.startswith("$input."):
                    key = binding.replace("$input.", "")
                    resolved_kwargs[param] = initial_input.get(key, initial_input.get("raw", initial_input))
                elif isinstance(binding, str) and binding.startswith("$stages."):
                    parts = binding.split(".")
                    # e.g. $stages.<stage_id>.result
                    src_stage_id = parts[1]
                    resolved_kwargs[param] = stage_results.get(src_stage_id)
                else:
                    resolved_kwargs[param] = binding

            t_stage_start = time.perf_counter()
            try:
                out = stage.tool_fn(**resolved_kwargs)
                stage_results[stage_id] = out
                duration = round(time.perf_counter() - t_stage_start, 5)
                stage_telemetry.append({
                    "stage_id": stage_id,
                    "tool": stage.tool_name,
                    "success": True,
                    "duration_sec": duration,
                    "output_preview": str(out)[:120],
                })
            except Exception as e:
                stage_results[stage_id] = f"Error: {e}"
                stage_telemetry.append({
                    "stage_id": stage_id,
                    "tool": stage.tool_name,
                    "success": False,
                    "error": str(e),
                })

        final_stage_id = dag.execution_order[-1]
        final_result = stage_results.get(final_stage_id)

        # Cryptographic Merkle Root over execution outputs
        merkle_blocks = [f"{s}:{stage_results.get(s)}" for s in dag.execution_order]
        merkle_root = hashlib.sha256("::".join(merkle_blocks).encode("utf-8")).hexdigest()[:16]

        total_duration = round(time.perf_counter() - t_start, 4)

        return {
            "pipeline_id": dag.pipeline_id,
            "goal": dag.goal,
            "final_result": final_result,
            "stage_results": stage_results,
            "stage_telemetry": stage_telemetry,
            "merkle_root": f"0x{merkle_root}",
            "total_duration_sec": total_duration,
            "success": all(t.get("success", False) for t in stage_telemetry),
        }
