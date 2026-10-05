"""
SICA: Self-Improving Coding Agent Mutation & Scaffolding Engine for O0.
Adapted from HORIZONTAL's SICA research and production patterns.

Provides deterministic keep-or-revert code mutation arbitration:
1. AST syntax parsing and validation.
2. AST node counting and cyclomatic bloat penalty calculation.
3. Significance epsilon boundary arbitration (default Delta >= 0.02).
4. Deterministic SHA-256 signature sealing for tamper-evident provenance.
5. Automated AST code mutation operators (memoization, defensive guards, loop optimizations).
"""

from __future__ import annotations

import ast
import copy
import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class MutationEvaluationResult:
    decision: str  # "KEEP" or "REVERT"
    effective_score: float
    delta: float
    syntax_valid: bool
    ast_valid: bool
    base_ast_nodes: int
    cand_ast_nodes: int
    node_expansion_ratio: float
    bloat_penalty: float
    deterministic_signature: str
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class _MemoizationInjector(ast.NodeTransformer):
    """Injects @functools.lru_cache(maxsize=128) onto eligible pure functions."""

    def __init__(self):
        super().__init__()
        self.injected = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        # Check if already decorated
        has_lru = any(
            (isinstance(d, ast.Name) and d.id == "lru_cache")
            or (isinstance(d, ast.Attribute) and d.attr == "lru_cache")
            or (isinstance(d, ast.Call) and getattr(d.func, "id", "") == "lru_cache")
            for d in node.decorator_list
        )
        if not has_lru and len(node.args.args) >= 1:
            decorator = ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="functools", ctx=ast.Load()),
                    attr="lru_cache",
                    ctx=ast.Load(),
                ),
                args=[],
                keywords=[ast.keyword(arg="maxsize", value=ast.Constant(value=128))],
            )
            node.decorator_list.insert(0, decorator)
            self.injected = True
        return self.generic_visit(node)


class _DefensiveGuardInjector(ast.NodeTransformer):
    """Wraps bare function bodies in defensive try-except blocks returning safe fallbacks."""

    def __init__(self):
        super().__init__()
        self.injected = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        if len(node.body) > 0 and not isinstance(node.body[0], ast.Try):
            try_node = ast.Try(
                body=node.body,
                handlers=[
                    ast.ExceptHandler(
                        type=ast.Name(id="Exception", ctx=ast.Load()),
                        name="ex",
                        body=[ast.Return(value=ast.Constant(value=None))],
                    )
                ],
                orelse=[],
                finalbody=[],
            )
            node.body = [try_node]
            self.injected = True
        return self.generic_visit(node)


class SICAMutationEngine:
    """Self-Improving Coding Agent Mutation & Scaffolding Engine."""

    def __init__(self, significance_epsilon: float = 0.02, bloat_ratio_threshold: float = 2.5):
        self.significance_epsilon = significance_epsilon
        self.bloat_ratio_threshold = bloat_ratio_threshold

    def evaluate_mutation(
        self,
        baseline_code: str,
        candidate_code: str,
        test_scores: Optional[List[float]] = None,
        baseline_score: float = 1.0,
    ) -> MutationEvaluationResult:
        """
        Evaluates a candidate code scaffolding mutation using AST complexity analysis,
        syntax validation, bloat penalties, and keep-or-revert arbitration.
        """
        if not candidate_code or not candidate_code.strip():
            return MutationEvaluationResult(
                decision="REVERT",
                effective_score=0.0,
                delta=-1.0,
                syntax_valid=False,
                ast_valid=False,
                base_ast_nodes=0,
                cand_ast_nodes=0,
                node_expansion_ratio=0.0,
                bloat_penalty=0.0,
                deterministic_signature="0x0000000000000000",
                reason="Candidate code is empty",
            )

        # 1. AST Syntax Validation
        try:
            cand_tree = ast.parse(candidate_code)
            syntax_valid = True
        except SyntaxError as se:
            sig_input = f"{candidate_code}:syntax_error:REVERT"
            sig = hashlib.sha256(sig_input.encode("utf-8")).hexdigest()[:16]
            return MutationEvaluationResult(
                decision="REVERT",
                effective_score=0.0,
                delta=-1.0,
                syntax_valid=False,
                ast_valid=False,
                base_ast_nodes=0,
                cand_ast_nodes=0,
                node_expansion_ratio=0.0,
                bloat_penalty=0.0,
                deterministic_signature=f"0x{sig}",
                reason=f"SyntaxError: {se}",
            )

        # Count AST nodes for baseline
        base_nodes = 0
        try:
            base_tree = ast.parse(baseline_code)
            base_nodes = sum(1 for _ in ast.walk(base_tree))
        except Exception:
            base_nodes = 0

        cand_nodes = sum(1 for _ in ast.walk(cand_tree))
        node_ratio = round(cand_nodes / (base_nodes or 1), 3)

        # 2. Performance Metric Delta & Bloat Penalty
        scores = test_scores or [1.0]
        avg_score = sum(scores) / len(scores)

        # Penalize extreme code bloat (>2.5x node expansion without proportional test gain)
        bloat_penalty = 0.0
        if node_ratio > self.bloat_ratio_threshold:
            bloat_penalty = round((node_ratio - self.bloat_ratio_threshold) * 0.1, 4)

        effective_score = round(max(0.0, avg_score - bloat_penalty), 5)
        delta = round(effective_score - baseline_score, 5)

        # 3. Keep-or-Revert Decision Boundary
        decision = "KEEP" if delta >= self.significance_epsilon else "REVERT"
        reason = (
            f"Gain {delta:.4f} >= epsilon {self.significance_epsilon}"
            if decision == "KEEP"
            else f"Gain {delta:.4f} < epsilon {self.significance_epsilon} (bloat penalty: {bloat_penalty})"
        )

        # 4. Deterministic Cryptographic Signature
        sig_input = f"{candidate_code}:{effective_score}:{decision}"
        sig = hashlib.sha256(sig_input.encode("utf-8")).hexdigest()[:16]

        return MutationEvaluationResult(
            decision=decision,
            effective_score=effective_score,
            delta=delta,
            syntax_valid=syntax_valid,
            ast_valid=syntax_valid,
            base_ast_nodes=base_nodes,
            cand_ast_nodes=cand_nodes,
            node_expansion_ratio=node_ratio,
            bloat_penalty=bloat_penalty,
            deterministic_signature=f"0x{sig}",
            reason=reason,
        )

    def apply_memoization_mutation(self, source_code: str) -> Tuple[str, bool]:
        """Injects @functools.lru_cache(maxsize=128) onto eligible functions in AST."""
        try:
            tree = ast.parse(source_code)
            injector = _MemoizationInjector()
            modified = injector.visit(tree)
            if injector.injected:
                # Ensure functools is imported
                has_import = any(
                    isinstance(stmt, ast.Import) and any(alias.name == "functools" for alias in stmt.names)
                    for stmt in modified.body
                )
                if not has_import:
                    import_node = ast.Import(names=[ast.alias(name="functools")])
                    modified.body.insert(0, import_node)
                ast.fix_missing_locations(modified)
                return ast.unparse(modified), True
        except Exception:
            pass
        return source_code, False

    def apply_defensive_guard_mutation(self, source_code: str) -> Tuple[str, bool]:
        """Injects defensive try-except guards into bare functions in AST."""
        try:
            tree = ast.parse(source_code)
            injector = _DefensiveGuardInjector()
            modified = injector.visit(tree)
            if injector.injected:
                ast.fix_missing_locations(modified)
                return ast.unparse(modified), True
        except Exception:
            pass
        return source_code, False

    def benchmark_candidate_mutations(
        self,
        baseline_code: str,
        candidates: List[Dict[str, Any]],
        baseline_score: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Benchmarks a batch of candidate code mutations against baseline.
        Returns ranked evaluations and identifies the best winning candidate.
        """
        evaluations: List[Dict[str, Any]] = []

        for cand in candidates:
            code = cand.get("code", "")
            scores = cand.get("test_scores", [1.0])
            eval_res = self.evaluate_mutation(
                baseline_code=baseline_code,
                candidate_code=code,
                test_scores=scores,
                baseline_score=baseline_score,
            )
            evaluations.append({
                "candidate_id": cand.get("id", "cand"),
                "decision": eval_res.decision,
                "effective_score": eval_res.effective_score,
                "delta": eval_res.delta,
                "bloat_penalty": eval_res.bloat_penalty,
                "signature": eval_res.deterministic_signature,
                "code": code,
                "reason": eval_res.reason,
            })

        # Rank candidates by effective score descending
        evaluations.sort(key=lambda x: x["effective_score"], reverse=True)
        winning_candidates = [e for e in evaluations if e["decision"] == "KEEP"]
        best_candidate = winning_candidates[0] if winning_candidates else None

        return {
            "total_candidates": len(candidates),
            "evaluations": evaluations,
            "best_candidate": best_candidate,
            "has_promoted_winner": best_candidate is not None,
        }
