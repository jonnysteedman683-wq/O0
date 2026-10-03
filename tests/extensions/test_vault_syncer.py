"""Tests for VaultSyncer and SynapticReasoningLoop (extensions/spatial_memory/syncer.py)."""
from __future__ import annotations

from pathlib import Path

from extensions.spatial_memory import SynapticReasoningLoop, VaultSyncer


def test_vault_syncer_writes_markdown_report(tmp_path: Path):
    vault = tmp_path / "vault"
    syncer = VaultSyncer(vault_path=vault)

    report_path = syncer.write_task_report(
        task="echo 'training complete'",
        passed=True,
        steps=[{"step": "echo 'training complete'", "verdict": True, "attempts": 1, "output": "training complete"}],
        personal_note="Trained loss down to 0.04. Model ready for testing.",
        station="ML",
        priority=8,
    )

    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "Task Report:" in content
    assert "station: ML" in content
    assert "priority: 8" in content
    assert "Trained loss down to 0.04" in content
    assert "SUCCESS" in content


def test_synaptic_reasoning_loop_executes_and_reports(tmp_path: Path):
    vault = tmp_path / "vault"
    syncer = VaultSyncer(vault_path=vault)
    loop = SynapticReasoningLoop(syncer=syncer)

    res = loop.run(
        task="python -c \"print('unit_test_passed')\"",
        personal_note="Tested self-modification verification logic.",
        station="TESTS",
    )

    assert res["passed"] is True
    assert "vault_report" in res
    report_file = Path(res["vault_report"])
    assert report_file.exists()
    text = report_file.read_text(encoding="utf-8")
    assert "Tested self-modification verification logic." in text
    assert "station: TESTS" in text
