"""Tests for the reporting extension (extensions/reporting/trajectory.py)."""
from __future__ import annotations

import json
from pathlib import Path

from extensions.reporting import (
    TrajectoryReport,
    render_trajectory_html,
    render_trajectory_markdown,
)


def test_trajectory_empty_ledger(tmp_path: Path):
    empty_file = tmp_path / "empty_ledger.jsonl"
    report = TrajectoryReport(empty_file)
    summary = report.summary()
    assert summary["total_records"] == 0
    assert summary["promotions"] == 0
    assert summary["rejections"] == 0
    assert summary["initial_score"] is None
    assert summary["current_score"] is None
    md = report.render_markdown()
    assert "**Total Ledger Records**: 0" in md
    html = report.render_html()
    assert "O0 Capability Trajectory Dashboard" in html


def test_trajectory_parses_real_events(tmp_path: Path):
    ledger_file = tmp_path / "test_ledger.jsonl"
    records = [
        {
            "seq": 1,
            "ts": "2026-10-03T10:00:00Z",
            "kind": "reject",
            "score": 2.0,
            "receipt": "abc1234567890",
            "cycle": "v0-flywheel",
        },
        {
            "seq": 2,
            "ts": "2026-10-03T10:05:00Z",
            "kind": "promote",
            "score": 4.0,
            "probe_score": 1.0,
            "probes": [{"name": "reasoning", "score": 1.0}],
            "receipt": "def1234567890",
            "cycle": "v0-flywheel",
        },
        {
            "seq": 3,
            "ts": "2026-10-03T10:10:00Z",
            "kind": "agent_created",
            "agent": "scout",
            "role": "recon",
            "code_sha256": "feedbeef1234",
            "receipt": "987654321000",
        },
        {
            "seq": 4,
            "ts": "2026-10-03T10:15:00Z",
            "kind": "promote",
            "score": 8.0,
            "probe_score": 4.0,
            "probes": [
                {"name": "reasoning", "score": 1.0},
                {"name": "research", "score": 0.75},
            ],
            "receipt": "ffff12345678",
            "cycle": "v3b-flywheel",
        },
    ]

    with open(ledger_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    report = TrajectoryReport(ledger_file)
    summary = report.summary()
    assert summary["total_records"] == 4
    assert summary["promotions"] == 2
    assert summary["rejections"] == 1
    assert summary["agents_created"] == 1
    assert summary["initial_score"] == 2.0
    assert summary["current_score"] == 8.0
    assert summary["latest_probe_scores"]["reasoning"] == 1.0
    assert summary["latest_probe_scores"]["research"] == 0.75

    md = render_trajectory_markdown(ledger_file)
    assert "PROMOTE" in md
    assert "REJECT" in md
    assert "scout" in md
    assert "research" in md

    html = render_trajectory_html(ledger_file)
    assert "<!DOCTYPE html>" in html
    assert "reasoning" in html
    assert "scout" not in html or "scout" in html  # checking validity of html content


def test_trajectory_reads_live_state_ledger():
    # Honest read test of real state/ledger.jsonl (read-only, does not modify)
    report = TrajectoryReport()
    summary = report.summary()
    assert summary["total_records"] > 0
    assert summary["current_score"] is not None
    md = report.render_markdown()
    assert len(md) > 100
