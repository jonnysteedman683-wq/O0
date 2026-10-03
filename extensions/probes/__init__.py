"""Extension capability probes (mirror o0/probes.py: Probe + ProbeResult)."""
from __future__ import annotations

from o0.probes import Probe, ProbeResult

from .research import ResearchProbe

# Registry of extension probes: name -> Probe class.
EXTENSION_PROBES: dict[str, type[Probe]] = {
    ResearchProbe.name: ResearchProbe,
}


def run_extension_probes() -> list[ProbeResult]:
    """Run every registered extension probe with default settings."""
    return [cls().run() for cls in EXTENSION_PROBES.values()]


__all__ = ["EXTENSION_PROBES", "ResearchProbe", "run_extension_probes"]
