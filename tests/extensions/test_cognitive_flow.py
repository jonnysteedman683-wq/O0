"""Tests for CognitiveFlowController (extensions/cognitive_flow/controller.py)."""
from __future__ import annotations

from extensions.cognitive_flow import (
    CognitiveFlowController,
    FlowState,
)


def test_initial_flow_state():
    ctrl = CognitiveFlowController()
    assert ctrl.metrics.current_state == FlowState.FLOW
    assert ctrl.should_batch_execute() is True


def test_failure_drops_immediately_to_deliberate():
    ctrl = CognitiveFlowController()
    state = ctrl.update_state(step_passed=False)
    assert state == FlowState.DELIBERATE
    assert ctrl.should_batch_execute() is False
    assert ctrl.metrics.deliberations_triggered == 1
    assert ctrl.metrics.consecutive_successes == 0


def test_recovering_back_to_flow():
    ctrl = CognitiveFlowController(flow_ramp_threshold=2)
    # Trigger drop
    ctrl.update_state(step_passed=False)
    assert ctrl.metrics.current_state == FlowState.DELIBERATE

    # 1 success -> still deliberate
    state1 = ctrl.update_state(step_passed=True, uncertainty=0.1)
    assert state1 == FlowState.DELIBERATE

    # 2 consecutive successes -> returns to FLOW mode!
    state2 = ctrl.update_state(step_passed=True, uncertainty=0.0)
    assert state2 == FlowState.FLOW
    assert ctrl.should_batch_execute() is True


def test_high_uncertainty_prevents_flow_ramp():
    ctrl = CognitiveFlowController(flow_ramp_threshold=2, confidence_threshold=0.8)
    # Step passes but with very high uncertainty (uncertainty=0.9 -> instant_confidence=0.1)
    ctrl.update_state(step_passed=True, uncertainty=0.9)
    ctrl.update_state(step_passed=True, uncertainty=0.9)
    # Confidence remains depressed, so it stays in DELIBERATE mode
    assert ctrl.metrics.current_state == FlowState.DELIBERATE
