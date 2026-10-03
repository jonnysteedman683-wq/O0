"""Agent probe_agent — created by O0 (v4 cross-stack agency)."""
from o0.reasoning import ReasoningLoop

ROLE = 'probe'
CONSTITUTION = 'probe-only'

def run(task: str) -> dict:
    """Execute a task through O0's reasoning loop."""
    return ReasoningLoop().run(task)
