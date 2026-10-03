"""Synapse package for inter-orchestrator communication."""
from __future__ import annotations

from .bridge import SynapseBridge, SynapseMessage
from .net_bridge import SynapseRPCClient, SynapseRPCServer

__all__ = ["SynapseBridge", "SynapseMessage", "SynapseRPCServer", "SynapseRPCClient"]
