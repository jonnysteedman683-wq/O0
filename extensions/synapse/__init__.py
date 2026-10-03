"""Synapse package for inter-orchestrator communication."""
from __future__ import annotations

from .bridge import SynapseBridge, SynapseMessage

__all__ = ["SynapseBridge", "SynapseMessage"]
