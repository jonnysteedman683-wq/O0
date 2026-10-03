"""O0's self-model: who it is, what it can do, and its governing invariants."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

REPO_ROOT = Path(os.path.dirname(os.path.abspath(__file__))).parent

CONSTITUTION_PATH = REPO_ROOT / "CONSTITUTION.md"
BLUEPRINT_PATH = REPO_ROOT / "BLUEPRINT.md"


def _sha256_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Identity:
    """A snapshot of O0's immutable identity at a point in time."""

    name = "O0"
    ambition = "the strongest AI to ever exist"

    def __init__(self) -> None:
        self.constitution_path = CONSTITUTION_PATH
        self.blueprint_path = BLUEPRINT_PATH

    @property
    def constitution_hash(self) -> str:
        return _sha256_of_file(self.constitution_path)

    @property
    def blueprint_hash(self) -> str:
        return _sha256_of_file(self.blueprint_path)

    def manifest(self) -> dict:
        """A verifiable snapshot of O0's self-model."""
        return {
            "name": self.name,
            "ambition": self.ambition,
            "constitution_path": str(self.constitution_path),
            "constitution_sha256": self.constitution_hash,
            "blueprint_path": str(self.blueprint_path),
            "blueprint_sha256": self.blueprint_hash,
        }
