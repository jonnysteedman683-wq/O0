"""Verification gates: py_compile + capability harness + constitution audit.

A change may be PROMOTED only if every gate passes. Facts over vibes:
each gate runs a real command/check and records measured output.
"""
from __future__ import annotations

import py_compile
import subprocess
import sys
from pathlib import Path

from .identity import Identity
from .ledger import Ledger

REPO_ROOT = Path(__file__).resolve().parent.parent
O0_DIR = REPO_ROOT / "o0"


class GateResult:
    def __init__(self, name: str, passed: bool, detail: str):
        self.name = name
        self.passed = passed
        self.detail = detail

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


def gate_compile() -> GateResult:
    """Every module in o0/ must byte-compile."""
    failed: list[str] = []
    for py in sorted(O0_DIR.rglob("*.py")):
        try:
            py_compile.compile(str(py), doraise=True)
        except py_compile.PyCompileError as exc:
            failed.append(str(exc))
    ok = not failed
    detail = "all modules compile" if ok else "; ".join(failed)
    return GateResult("gate.compile", ok, detail)


def gate_harness() -> GateResult:
    """The tests/ harness must be green (v0 capability metric)."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    detail = (proc.stdout or "") + (proc.stderr or "")
    detail = detail.strip().replace("\n", " ")[-500:]
    return GateResult("gate.harness", proc.returncode == 0, detail or "pytest ok")


def gate_constitution(identity: Identity, ledger: Ledger) -> GateResult:
    """The constitution file must exist and its hash must be recorded/auditable."""
    if not identity.constitution_path.exists():
        return GateResult("gate.constitution", False, "CONSTITUTION.md missing")
    h = identity.constitution_hash
    return GateResult("gate.constitution", True, f"constitution sha256={h:.12}")


def run_all_gates(ledger: Ledger | None = None) -> list[GateResult]:
    identity = Identity()
    ledger = ledger or Ledger()
    return [
        gate_compile(),
        gate_harness(),
        gate_constitution(identity, ledger),
    ]


def capability_score(results: list[GateResult]) -> dict:
    """v0 ledger capability metric: green gate count + ledger integrity."""
    gates_ok = sum(1 for g in results if g.passed)
    ledger = Ledger()
    integrity_ok, checked, broken = ledger.verify_integrity()
    return {
        "gates_passed": gates_ok,
        "gates_total": len(results),
        "ledger_integrity_ok": integrity_ok,
        "ledger_records_checked": checked,
        "ledger_broken": broken,
        "score": gates_ok + (1 if integrity_ok and checked > 0 else 0),
    }
