"""
Multi-Objective Pareto Fitness Engine for O0 Tri-Coding Arena.
Adapted from HORIZONTAL's NSGA-II and GEPA paradigms.

Evaluates candidates along multi-dimensional objective vectors:
- Capability / Score (maximize)
- Latency / Speed (maximize score / minimize duration)
- Complexity / Compression (minimize node bloat / maximize compactness)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence


@dataclass
class ParetoCandidate:
    candidate_id: str
    objectives: Dict[str, float]  # All values normalized where higher is better [0.0, 1.0]
    metadata: Dict[str, Any] = field(default_factory=dict)
    rank: int = 0
    crowding_distance: float = 0.0


def dominates(cand_a: ParetoCandidate, cand_b: ParetoCandidate, objective_keys: Sequence[str]) -> bool:
    """
    Pareto Domination:
    cand_a dominates cand_b iff cand_a is >= cand_b on all objectives
    and strictly > cand_b on at least one objective.
    """
    greater_or_equal = True
    strictly_greater = False

    for key in objective_keys:
        val_a = cand_a.objectives.get(key, 0.0)
        val_b = cand_b.objectives.get(key, 0.0)
        if val_a < val_b:
            greater_or_equal = False
            break
        if val_a > val_b:
            strictly_greater = True

    return greater_or_equal and strictly_greater


def extract_pareto_frontier(
    candidates: Sequence[ParetoCandidate],
    objective_keys: Sequence[str]
) -> List[ParetoCandidate]:
    """
    Extracts the non-dominated Pareto frontier (Rank 1 solutions) from a set of candidates.
    """
    frontier: List[ParetoCandidate] = []

    for i, cand_a in enumerate(candidates):
        is_dominated = False
        for j, cand_b in enumerate(candidates):
            if i != j and dominates(cand_b, cand_a, objective_keys):
                is_dominated = True
                break
        if not is_dominated:
            cand_a.rank = 1
            frontier.append(cand_a)

    return frontier


def fast_non_dominated_sort(
    candidates: Sequence[ParetoCandidate],
    objective_keys: Sequence[str]
) -> List[List[ParetoCandidate]]:
    """
    NSGA-II Fast Non-Dominated Sorting Algorithm.
    Divides candidates into hierarchical Pareto fronts: Front 0 (Rank 1), Front 1 (Rank 2), etc.
    """
    population = list(candidates)
    if not population:
        return []

    domination_map: Dict[int, List[int]] = {i: [] for i in range(len(population))}
    dominated_count: Dict[int, int] = {i: 0 for i in range(len(population))}
    fronts_indices: List[List[int]] = [[]]

    for p in range(len(population)):
        for q in range(len(population)):
            if p == q:
                continue
            if dominates(population[p], population[q], objective_keys):
                domination_map[p].append(q)
            elif dominates(population[q], population[p], objective_keys):
                dominated_count[p] += 1

        if dominated_count[p] == 0:
            population[p].rank = 1
            fronts_indices[0].append(p)

    current_front_idx = 0
    while current_front_idx < len(fronts_indices) and fronts_indices[current_front_idx]:
        next_front: List[int] = []
        for p in fronts_indices[current_front_idx]:
            for q in domination_map[p]:
                dominated_count[q] -= 1
                if dominated_count[q] == 0:
                    population[q].rank = current_front_idx + 2
                    next_front.append(q)
        current_front_idx += 1
        if next_front:
            fronts_indices.append(next_front)

    result_fronts: List[List[ParetoCandidate]] = []
    for front_idx_list in fronts_indices:
        if front_idx_list:
            front = [population[idx] for idx in front_idx_list]
            _assign_crowding_distance(front, objective_keys)
            result_fronts.append(front)

    return result_fronts


def _assign_crowding_distance(front: List[ParetoCandidate], objective_keys: Sequence[str]) -> None:
    """Assigns NSGA-II crowding distances to preserve population diversity."""
    n = len(front)
    if n == 0:
        return
    if n <= 2:
        for ind in front:
            ind.crowding_distance = float("inf")
        return

    for ind in front:
        ind.crowding_distance = 0.0

    for key in objective_keys:
        front.sort(key=lambda x: x.objectives.get(key, 0.0))
        front[0].crowding_distance = float("inf")
        front[-1].crowding_distance = float("inf")

        val_min = front[0].objectives.get(key, 0.0)
        val_max = front[-1].objectives.get(key, 0.0)
        diff = val_max - val_min

        if diff == 0.0:
            continue

        for i in range(1, n - 1):
            if front[i].crowding_distance != float("inf"):
                prev_val = front[i - 1].objectives.get(key, 0.0)
                next_val = front[i + 1].objectives.get(key, 0.0)
                front[i].crowding_distance += (next_val - prev_val) / diff
