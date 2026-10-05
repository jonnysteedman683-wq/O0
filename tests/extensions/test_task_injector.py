"""Unit tests for the End-to-End Task Injector."""

from pathlib import Path

from extensions.tasks.injector import EndToEndTaskInjector


def test_end_to_end_mamba_audit_injection(tmp_path: Path):
    vault = tmp_path / "vault"
    stations = vault / "STATIONS" / "ML_STATION"
    stations.mkdir(parents=True)

    # Seed Mamba note in ML Station
    mamba_file = stations / "MAMBA_SELECTIVE_SSM.md"
    mamba_file.write_text(
        "---\ntitle: MAMBA_SELECTIVE_SSM\nstation: ML\npriority: 8\nquick_paths: []\ntags: [ssm, mamba]\n---\nMathematical formulation for selective scan.\n",
        encoding="utf-8",
    )

    injector = EndToEndTaskInjector(vault_path=vault)
    result = injector.run_mamba_audit_task()

    # 1. Overall verification
    assert result.passed is True
    assert "MAMBA_SELECTIVE_SSM" in result.spatial_nodes_retrieved

    # 2. Cognitive flow mode
    assert result.cognitive_mode == "DELIBERATE"

    # 3. ADAS topology mode
    assert result.topology_mode == "adversarial_colosseum"

    # 4. Circuit breaker tier
    assert result.circuit_tier == "TIER_1_DIRECT"
    assert result.trajectory_hash.startswith("0x")

    # 5. Vault Syncer report
    assert result.report_path is not None
    report_file = Path(result.report_path)
    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "mamba_ssm_numerical_stability_audit" in content
    assert "CERTIFIED_NUMERICALLY_STABLE" in content
    assert "Adversarial Colosseum proved" in content
