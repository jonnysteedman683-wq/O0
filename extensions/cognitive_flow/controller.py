"""Cognitive Flow Controller for O0 (inspired by HORIZONTAL ML research).

Implements dynamic flow states for reasoning and execution:
1. FLOW MODE: High confidence, low uncertainty -> batch-executes steps without
   unnecessary pause, disk sync, or intermediate friction.
2. DELIBERATE MODE: Low confidence, anomaly, or failure -> drops down to
   fine-grained step-by-step reflection, retry bounding, and memory lookups.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from o0.reasoning import StepResult, Verdict


class FlowState(str, Enum):
    FLOW = "FLOW"                # High speed, batch pipelining
    DELIBERATE = "DELIBERATE"    # Fine-grained step-by-step reflection


@dataclass
class FlowMetrics:
    current_state: FlowState = FlowState.FLOW
    consecutive_successes: int = 0
    total_steps_executed: int = 0
    deliberations_triggered: int = 0
    confidence_score: float = 1.0


class CognitiveFlowController:
    """Dynamically balances execution velocity against verification rigor."""

    def __init__(
        self,
        confidence_threshold: float = 0.7,
        flow_ramp_threshold: int = 2,
    ):
        self.confidence_threshold = confidence_threshold
        self.flow_ramp_threshold = flow_ramp_threshold
        self.metrics = FlowMetrics()

    def update_state(self, step_passed: bool, uncertainty: float = 0.0) -> FlowState:
        """Adjusts cognitive flow state based on outcome and uncertainty."""
        self.metrics.total_steps_executed += 1
        
        # Uncertainty penalizes confidence: confidence = (1.0 - uncertainty)
        instant_confidence = max(0.0, min(1.0, 1.0 - uncertainty))
        
        if not step_passed:
            # Immediate drop into DELIBERATE mode on any failure
            self.metrics.current_state = FlowState.DELIBERATE
            self.metrics.consecutive_successes = 0
            self.metrics.deliberations_triggered += 1
            self.metrics.confidence_score = 0.0
            return self.metrics.current_state

        # On success, smoothly update confidence
        self.metrics.consecutive_successes += 1
        self.metrics.confidence_score = (
            0.5 * self.metrics.confidence_score + 0.5 * instant_confidence
        )

        # Promote to FLOW mode if consecutive successes threshold met
        if (
            self.metrics.consecutive_successes >= self.flow_ramp_threshold
            and self.metrics.confidence_score >= self.confidence_threshold
        ):
            self.metrics.current_state = FlowState.FLOW
        else:
            self.metrics.current_state = FlowState.DELIBERATE

        return self.metrics.current_state

    def should_batch_execute(self) -> bool:
        """Returns True if the engine is running in smooth high-speed Flow Mode."""
        return self.metrics.current_state == FlowState.FLOW
