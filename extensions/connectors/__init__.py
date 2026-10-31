"""Cross-stack connectors for O0 (Antigravity territory).

- ``unisync``: O0's client for the shared UniSync ledger Sebastian and Lestinxor already use.
- ``github``: GitHub-aware stack connectors that probe each project's repo instead of a local folder.
- ``dispatch``: human-gated hand-off of tasks to other agents via ``task.request`` envelopes.

Everything here is opt-in (env vars), stdlib-only and fail-open: a missing key or an unreachable
service returns an honest status instead of raising into O0's flywheel.
"""

from .dispatch import Dispatcher, DispatchError
from .github import STACK_REPOS, GitHubConnector, github_stack
from .unisync import UnisyncClient, UnisyncError

__all__ = [
    "STACK_REPOS",
    "DispatchError",
    "Dispatcher",
    "GitHubConnector",
    "UnisyncClient",
    "UnisyncError",
    "github_stack",
]
