"""Unit tests for Autonomous Continuous Self-Evolution Daemon."""

from pathlib import Path

from extensions.evolution.autonomous_daemon import AutonomousEvolutionDaemon


def test_evolution_daemon_promotes_winning_mutation(tmp_path: Path):
    vault = tmp_path / "vault"
    daemon = AutonomousEvolutionDaemon(vault_path=vault, significance_epsilon=0.02)

    # Mock candidate that improves score from 1.00 to 1.10 (Delta = +0.10 >= 0.02)
    def winning_candidate():
        baseline = "def solver(x): return x"
        candidate = "def solver(x): return x * 2"
        score = 1.10
        return baseline, candidate, score

    res = daemon.step_pulse(mock_candidate_fn=winning_candidate)

    assert res.status == "PROMOTED"
    assert res.delta_score >= 0.02
    assert res.pareto_dominant is True
    assert res.mutation_signature.startswith("0x")
    assert daemon.promotions_count == 1
    assert daemon.total_pulses == 1

    # Verify vault report was written
    assert res.report_path is not None
    report_file = Path(res.report_path)
    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "PROMOTED" in content
    assert "evolution_" in content


def test_evolution_daemon_reverts_regressive_mutation(tmp_path: Path):
    vault = tmp_path / "vault"
    daemon = AutonomousEvolutionDaemon(vault_path=vault, significance_epsilon=0.02)

    # Mock candidate that regresses score to 0.85 (Delta = -0.15)
    def regressive_candidate():
        baseline = "def solver(x): return x"
        candidate = "def solver(x): return 0"
        score = 0.85
        return baseline, candidate, score

    res = daemon.step_pulse(mock_candidate_fn=regressive_candidate)

    assert res.status == "REVERTED"
    assert res.delta_score < 0.02
    assert daemon.reversions_count == 1
    assert daemon.promotions_count == 0


def test_evolution_daemon_default_memoization_pulse(tmp_path: Path):
    vault = tmp_path / "vault"
    daemon = AutonomousEvolutionDaemon(vault_path=vault)

    # Runs with default autonomous self-mutation operator (injects @lru_cache)
    res = daemon.step_pulse(target_goal="Self-optimize computation loop with AST memoization")

    assert res.status == "PROMOTED"
    assert res.delta_score >= 0.02
    assert res.circuit_tier in ("TIER_1_DIRECT", "TIER_2_CHAMBER_SANDBOX")
    assert len(daemon.pulse_history) == 1
