"""Unit tests for SICA Self-Improving Coding Agent Mutation Engine."""

from extensions.sica.mutation_engine import SICAMutationEngine


def test_sica_rejects_syntax_errors():
    engine = SICAMutationEngine()
    baseline = "def solver(x): return x * 2"
    broken_candidate = "def solver(x): return x * : error"

    res = engine.evaluate_mutation(baseline, broken_candidate, test_scores=[1.5])
    assert res.decision == "REVERT"
    assert res.syntax_valid is False
    assert "SyntaxError" in res.reason


def test_sica_keeps_significant_mutation():
    engine = SICAMutationEngine(significance_epsilon=0.02)
    baseline = "def solver(x): return x * 2"
    # Optimized candidate scoring 1.08 (Delta = 0.08 >= 0.02)
    candidate = "def solver(x): return x << 1"

    res = engine.evaluate_mutation(baseline, candidate, test_scores=[1.08], baseline_score=1.0)
    assert res.decision == "KEEP"
    assert res.delta >= 0.02
    assert res.syntax_valid is True
    assert res.deterministic_signature.startswith("0x")


def test_sica_reverts_sub_epsilon_mutation():
    engine = SICAMutationEngine(significance_epsilon=0.02)
    baseline = "def solver(x): return x * 2"
    # Marginal candidate scoring 1.01 (Delta = 0.01 < 0.02)
    candidate = "def solver(x): return x + x"

    res = engine.evaluate_mutation(baseline, candidate, test_scores=[1.01], baseline_score=1.0)
    assert res.decision == "REVERT"
    assert res.delta < 0.02


def test_sica_penalizes_extreme_code_bloat():
    engine = SICAMutationEngine(bloat_ratio_threshold=2.5)
    baseline = "def solver(x): return x * 2"

    # Heavily unrolled/bloated candidate (>4x AST node expansion)
    bloated_code = """
def solver(x):
    a = 1
    b = 2
    c = 3
    d = 4
    e = 5
    f = 6
    g = 7
    h = 8
    i = 9
    j = 10
    k = 11
    l = 12
    return x * 2
"""
    # Test score 1.05 would normally pass, but bloat penalty drops effective score
    res = engine.evaluate_mutation(baseline, bloated_code, test_scores=[1.05], baseline_score=1.0)
    assert res.node_expansion_ratio > 2.5
    assert res.bloat_penalty > 0.0
    assert res.decision == "REVERT"


def test_apply_memoization_mutation():
    engine = SICAMutationEngine()
    source = "def compute_factorial(n):\n    return 1 if n <= 1 else n * compute_factorial(n - 1)"

    mutated, changed = engine.apply_memoization_mutation(source)
    assert changed is True
    assert "lru_cache" in mutated
    assert "functools" in mutated


def test_apply_defensive_guard_mutation():
    engine = SICAMutationEngine()
    source = "def fragile_calc(x):\n    return 100 / x"

    mutated, changed = engine.apply_defensive_guard_mutation(source)
    assert changed is True
    assert "try:" in mutated
    assert "except Exception" in mutated


def test_benchmark_candidate_mutations_batch():
    engine = SICAMutationEngine(significance_epsilon=0.02)
    baseline = "def solver(x): return x"

    candidates = [
        {"id": "cand_winner", "code": "def solver(x): return x * 2", "test_scores": [1.12]},
        {"id": "cand_sub_epsilon", "code": "def solver(x): return x + 0", "test_scores": [1.01]},
        {"id": "cand_broken", "code": "def solver(x: broken", "test_scores": [1.5]},
    ]

    report = engine.benchmark_candidate_mutations(baseline, candidates, baseline_score=1.0)
    assert report["total_candidates"] == 3
    assert report["has_promoted_winner"] is True
    assert report["best_candidate"]["candidate_id"] == "cand_winner"
    assert report["best_candidate"]["decision"] == "KEEP"
