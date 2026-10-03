"""Enhanced Synaptic Reasoning Loop with automatic Vault Sync & Reporting."""
from __future__ import annotations

from typing import Any

from o0.memory import Memory
from o0.reasoning import ReasoningLoop, ShellExecutor
from extensions.spatial_memory.syncer import VaultSyncer


class SynapticReasoningLoop(ReasoningLoop):
    """Extends O0's reasoning loop with mandatory Obsidian vault reporting."""

    def __init__(
        self,
        memory: Memory | None = None,
        max_retries: int = 2,
        executor: object | None = None,
        syncer: VaultSyncer | None = None,
    ):
        super().__init__(memory=memory, max_retries=max_retries, executor=executor)
        self.syncer = syncer or VaultSyncer()

    def run(self, task: str, personal_note: str = "", station: str = "TASKS") -> dict[str, Any]:
        """Runs the task cycle, extracts lessons, and writes a report to O0-DIRECTORY."""
        result = super().run(task)

        # Generate reflection if not provided
        if not personal_note:
            if result["passed"]:
                personal_note = (
                    f"Task succeeded smoothly. Verified execution without regressions. "
                    f"Evolved execution confidence."
                )
            else:
                personal_note = (
                    f"Task encountered friction during step verification. "
                    f"Recorded failure trace for future reflection."
                )

        # Write report step into O0-DIRECTORY
        report_path = self.syncer.write_task_report(
            task=task,
            passed=result["passed"],
            steps=result["steps"],
            personal_note=personal_note,
            station=station,
        )
        result["vault_report"] = str(report_path)
        return result
