"""Capability trajectory analysis and report generator for O0.

Reads state/ledger.jsonl (read-only) and renders capability metrics,
promotion timelines, gate successes, agent creation records, and
probe trajectories over time as Markdown or standalone HTML.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from o0.ledger import DEFAULT_LEDGER, Ledger


@dataclass
class TrajectorySnapshot:
    seq: int
    ts: str
    kind: str
    receipt: str
    score: float | None = None
    probe_score: float | None = None
    cycle: str = ""
    source_commit: str | None = None
    probes: dict[str, float | None] = field(default_factory=dict)
    gates: dict[str, bool] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


class TrajectoryReport:
    """Parses and renders O0 capability evolution across ledger events."""

    def __init__(self, ledger_path: Path | str = DEFAULT_LEDGER):
        self.ledger_path = Path(ledger_path)
        self.snapshots: list[TrajectorySnapshot] = []
        self._load()

    def _load(self) -> None:
        self.snapshots.clear()
        if not self.ledger_path.exists():
            return

        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    continue

                probes_map: dict[str, float | None] = {}
                for p in data.get("probes", []):
                    if isinstance(p, dict) and "name" in p:
                        probes_map[p["name"]] = p.get("score")

                gates_map: dict[str, bool] = {}
                for g in data.get("gates", []):
                    if isinstance(g, dict) and "name" in g:
                        gates_map[g["name"]] = bool(g.get("passed"))

                commits = data.get("commits") or {}
                source_commit = commits.get("source_commit") if isinstance(commits, dict) else None

                snap = TrajectorySnapshot(
                    seq=int(data.get("seq", len(self.snapshots) + 1)),
                    ts=str(data.get("ts", "")),
                    kind=str(data.get("kind", "unknown")),
                    receipt=str(data.get("receipt", "")),
                    score=float(data["score"]) if "score" in data and data["score"] is not None else None,
                    probe_score=float(data["probe_score"]) if "probe_score" in data and data["probe_score"] is not None else None,
                    cycle=str(data.get("cycle", "")),
                    source_commit=source_commit,
                    probes=probes_map,
                    gates=gates_map,
                    details=data,
                )
                self.snapshots.append(snap)

    def summary(self) -> dict[str, Any]:
        """Aggregate summary of trajectory stats."""
        total = len(self.snapshots)
        promotions = sum(1 for s in self.snapshots if s.kind == "promote")
        rejections = sum(1 for s in self.snapshots if s.kind == "reject")
        agents = sum(1 for s in self.snapshots if s.kind == "agent_created")

        initial_score: float | None = None
        current_score: float | None = None
        for s in self.snapshots:
            if s.score is not None:
                if initial_score is None:
                    initial_score = s.score
                current_score = s.score

        # Collect distinct probe names tracked
        all_probes: set[str] = set()
        for s in self.snapshots:
            all_probes.update(s.probes.keys())

        latest_probe_scores: dict[str, float | None] = {}
        for s in reversed(self.snapshots):
            for name, score in s.probes.items():
                if name not in latest_probe_scores:
                    latest_probe_scores[name] = score

        return {
            "total_records": total,
            "promotions": promotions,
            "rejections": rejections,
            "agents_created": agents,
            "initial_score": initial_score,
            "current_score": current_score,
            "tracked_probes": sorted(all_probes),
            "latest_probe_scores": latest_probe_scores,
        }

    def render_markdown(self) -> str:
        """Render markdown dashboard representing capability trajectory."""
        stats = self.summary()
        lines: list[str] = [
            "# O0 Capability Trajectory Report",
            "",
            "## Summary",
            f"- **Total Ledger Records**: {stats['total_records']}",
            f"- **Promotions**: {stats['promotions']} | **Rejections**: {stats['rejections']}",
            f"- **Agents Materialized**: {stats['agents_created']}",
            f"- **Score Progression**: `{stats['initial_score']}` → `{stats['current_score']}`",
            "",
            "## Active Probe Scores (Latest Snapshot)",
        ]

        if stats["latest_probe_scores"]:
            lines.append("| Probe | Latest Score |")
            lines.append("| :--- | :--- |")
            for name, score in sorted(stats["latest_probe_scores"].items()):
                score_str = f"{score:.2f}" if score is not None else "not measured"
                lines.append(f"| `{name}` | **{score_str}** |")
        else:
            lines.append("_No probe runs recorded in ledger._")

        lines.extend([
            "",
            "## Promotion & Rejection Timeline",
            "| Seq | Timestamp | Event | Cycle | Total Score | Probes Score | Receipt |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ])

        for s in self.snapshots:
            if s.kind in ("promote", "reject"):
                kind_badge = "✅ PROMOTE" if s.kind == "promote" else "❌ REJECT"
                score_str = f"{s.score:.1f}" if s.score is not None else "-"
                probe_score_str = f"{s.probe_score:.1f}" if s.probe_score is not None else "-"
                receipt_short = s.receipt[:8] if s.receipt else "-"
                lines.append(
                    f"| {s.seq} | {s.ts} | {kind_badge} | {s.cycle or '-'} | {score_str} | {probe_score_str} | `{receipt_short}` |"
                )

        # Agent creation history
        agent_snaps = [s for s in self.snapshots if s.kind == "agent_created"]
        if agent_snaps:
            lines.extend([
                "",
                "## Agents Materialized",
                "| Seq | Timestamp | Agent Name | Role | Code SHA256 |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ])
            for s in agent_snaps:
                name = s.details.get("agent", "unknown")
                role = s.details.get("role", "unknown")
                csha = s.details.get("code_sha256", "")[:8]
                lines.append(f"| {s.seq} | {s.ts} | `{name}` | {role} | `{csha}` |")

        lines.append("")
        return "\n".join(lines)

    def render_html(self) -> str:
        """Render self-contained HTML capability report with CSS styling."""
        stats = self.summary()
        md_text = self.render_markdown()

        # HTML generation with modern styling
        rows_timeline = ""
        for s in self.snapshots:
            if s.kind in ("promote", "reject"):
                badge_class = "badge-promote" if s.kind == "promote" else "badge-reject"
                score_str = f"{s.score:.1f}" if s.score is not None else "-"
                probe_score_str = f"{s.probe_score:.1f}" if s.probe_score is not None else "-"
                rows_timeline += f"""
                <tr>
                    <td>{s.seq}</td>
                    <td>{s.ts}</td>
                    <td><span class="{badge_class}">{s.kind.upper()}</span></td>
                    <td>{s.cycle or '-'}</td>
                    <td><strong>{score_str}</strong></td>
                    <td>{probe_score_str}</td>
                    <td><code>{s.receipt[:8]}</code></td>
                </tr>
                """

        probe_cards = ""
        for name, score in sorted(stats["latest_probe_scores"].items()):
            score_display = f"{score:.2f}" if score is not None else "N/A"
            probe_cards += f"""
            <div class="card">
                <div class="card-title">{name}</div>
                <div class="card-value">{score_display}</div>
            </div>
            """

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>O0 Capability Trajectory</title>
<style>
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        line-height: 1.6;
        color: #1a1a1a;
        max-width: 960px;
        margin: 40px auto;
        padding: 0 20px;
        background: #fdfdfd;
    }}
    h1, h2 {{ color: #111; border-bottom: 1px solid #eaeaea; padding-bottom: 8px; }}
    .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin: 20px 0; }}
    .card {{ background: #f7f9fa; border: 1px solid #e1e4e8; border-radius: 6px; padding: 16px; text-align: center; }}
    .card-title {{ font-size: 0.85em; color: #586069; text-transform: uppercase; letter-spacing: 0.5px; }}
    .card-value {{ font-size: 1.8em; font-weight: bold; margin-top: 8px; color: #0366d6; }}
    table {{ width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 0.95em; }}
    th, td {{ border: 1px solid #e1e4e8; padding: 10px 12px; text-align: left; }}
    th {{ background: #f6f8fa; }}
    .badge-promote {{ background: #28a745; color: white; padding: 3px 8px; border-radius: 12px; font-size: 0.8em; font-weight: bold; }}
    .badge-reject {{ background: #d73a49; color: white; padding: 3px 8px; border-radius: 12px; font-size: 0.8em; font-weight: bold; }}
    code {{ background: #f3f3f3; padding: 2px 4px; border-radius: 4px; font-family: monospace; }}
</style>
</head>
<body>
    <h1>O0 Capability Trajectory Dashboard</h1>
    <div class="stats-grid">
        <div class="card">
            <div class="card-title">Current Score</div>
            <div class="card-value">{stats['current_score']}</div>
        </div>
        <div class="card">
            <div class="card-title">Promotions</div>
            <div class="card-value">{stats['promotions']}</div>
        </div>
        <div class="card">
            <div class="card-title">Rejections</div>
            <div class="card-value">{stats['rejections']}</div>
        </div>
        <div class="card">
            <div class="card-title">Agents Created</div>
            <div class="card-value">{stats['agents_created']}</div>
        </div>
    </div>

    <h2>Active Capability Probes</h2>
    <div class="stats-grid">
        {probe_cards or "<p>No active probes recorded</p>"}
    </div>

    <h2>Evolution Timeline</h2>
    <table>
        <thead>
            <tr>
                <th>Seq</th>
                <th>Timestamp</th>
                <th>Event</th>
                <th>Cycle</th>
                <th>Score</th>
                <th>Probe Score</th>
                <th>Receipt</th>
            </tr>
        </thead>
        <tbody>
            {rows_timeline}
        </tbody>
    </table>
</body>
</html>
"""
        return html


def render_trajectory_markdown(ledger_path: Path | str = DEFAULT_LEDGER) -> str:
    return TrajectoryReport(ledger_path).render_markdown()


def render_trajectory_html(ledger_path: Path | str = DEFAULT_LEDGER) -> str:
    return TrajectoryReport(ledger_path).render_html()
