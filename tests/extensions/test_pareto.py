"""Unit tests for Pareto multi-objective fitness engine."""

from extensions.arena.pareto import (
    ParetoCandidate,
    dominates,
    extract_pareto_frontier,
    fast_non_dominated_sort,
)


def test_dominates_logic():
    keys = ["accuracy", "speed", "compression"]
    cand_a = ParetoCandidate("A", {"accuracy": 0.95, "speed": 0.80, "compression": 0.60})
    cand_b = ParetoCandidate("B", {"accuracy": 0.90, "speed": 0.80, "compression": 0.50})
    cand_c = ParetoCandidate("C", {"accuracy": 0.90, "speed": 0.90, "compression": 0.40})

    # A dominates B (higher accuracy and compression, equal speed)
    assert dominates(cand_a, cand_b, keys) is True
    assert dominates(cand_b, cand_a, keys) is False

    # A and C do not dominate each other (A has higher accuracy/compression, C has higher speed)
    assert dominates(cand_a, cand_c, keys) is False
    assert dominates(cand_c, cand_a, keys) is False


def test_extract_pareto_frontier():
    keys = ["score", "speed"]
    candidates = [
        ParetoCandidate("Fast", {"score": 0.70, "speed": 0.95}),
        ParetoCandidate("Accurate", {"score": 0.95, "speed": 0.70}),
        ParetoCandidate("Dominated", {"score": 0.60, "speed": 0.60}),
        ParetoCandidate("Equal_Leader", {"score": 0.95, "speed": 0.70}),
    ]

    frontier = extract_pareto_frontier(candidates, keys)
    front_ids = {c.candidate_id for c in frontier}

    assert "Fast" in front_ids
    assert "Accurate" in front_ids
    assert "Dominated" not in front_ids
    assert len(frontier) >= 2


def test_fast_non_dominated_sort_hierarchy():
    keys = ["score", "speed"]
    candidates = [
        ParetoCandidate("Top1", {"score": 1.0, "speed": 1.0}),
        ParetoCandidate("Mid1", {"score": 0.8, "speed": 0.8}),
        ParetoCandidate("Low1", {"score": 0.5, "speed": 0.5}),
    ]

    fronts = fast_non_dominated_sort(candidates, keys)
    assert len(fronts) == 3
    assert fronts[0][0].candidate_id == "Top1"
    assert fronts[0][0].rank == 1
    assert fronts[1][0].candidate_id == "Mid1"
    assert fronts[1][0].rank == 2
    assert fronts[2][0].candidate_id == "Low1"
    assert fronts[2][0].rank == 3
