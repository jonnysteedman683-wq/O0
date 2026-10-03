"""Vault Syncer and Task Report Generator for O0-DIRECTORY.

Syncs task execution and flywheel promotion results directly into
O0-DIRECTORY, formatting them with frontmatter, step summaries,
and personalized reflection notes from O0.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from extensions.spatial_memory import DEFAULT_VAULT_PATH, SpatialVaultNavigator


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sanitize_filename(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", name)[:50]


class VaultSyncer:
    """Synchronizes O0 execution history directly into O0-DIRECTORY."""

    def __init__(self, vault_path: Path | str = DEFAULT_VAULT_PATH):
        self.vault_path = Path(vault_path)
        self.navigator = SpatialVaultNavigator(self.vault_path)

    def write_task_report(
        self,
        task: str,
        passed: bool,
        steps: list[dict[str, Any]],
        personal_note: str = "",
        station: str = "TASKS",
        priority: int = 7,
    ) -> Path:
        """Writes a detailed task completion report directly into the vault."""
        reports_dir = self.vault_path / "STATIONS" / f"{station.upper()}_STATION" / "REPORTS"
        reports_dir.mkdir(parents=True, exist_ok=True)

        ts = _now_iso()
        safe_task = _sanitize_filename(task)
        filename = f"{ts.replace(':', '-')}_{safe_task}.md"
        report_file = reports_dir / filename

        status_str = "SUCCESS" if passed else "FAILURE"
        steps_md = []
        for i, s in enumerate(steps, 1):
            verdict_icon = "✅" if s.get("verdict") else "❌"
            steps_md.append(
                f"- **Step {i}**: `{s.get('step')}` | {verdict_icon} Attempts: {s.get('attempts', 1)}\n"
                f"  - *Detail*: {s.get('detail', '')}\n"
                f"  - *Output excerpt*: `{s.get('output', '').strip()[:150]}`"
            )

        content = f"""---
title: "Task Report: {task[:60]}"
priority: {priority}
station: {station.upper()}
status: "{status_str}"
timestamp: "{ts}"
quick_paths: [00_CORE_MAP, {station.upper()}_STATION]
tags: [task_report, {status_str.lower()}, {station.lower()}]
---

# 📋 O0 Task Execution Report: {status_str}

- **Task**: `{task}`
- **Completed At**: `{ts}`
- **Overall Verdict**: **{status_str}**

---

## 🔬 Execution Breakdown
{chr(10).join(steps_md) if steps_md else "_No distinct sub-steps recorded._"}

---

## 🧠 Personal Note & Evolutionary Reflection
> {personal_note or "Task executed and synchronized automatically by O0 reasoning loop."}

---
*Auto-synced into O0-DIRECTORY by Synaptic Vault Protocol.*
"""
        report_file.write_text(content, encoding="utf-8")
        return report_file
