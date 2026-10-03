"""Agent scout — created by O0 (v4 cross-stack agency)."""
from o0.reasoning import ReasoningLoop

ROLE = 'reconnaissance'
CONSTITUTION = "Serve O0's goals; never weaken the O0 constitution."

def run(task: str) -> dict:
    """Execute a task through O0's reasoning loop."""
    return ReasoningLoop().run(task)
