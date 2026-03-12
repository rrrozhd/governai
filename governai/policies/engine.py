from __future__ import annotations

from governai.models.policy import PolicyContext, PolicyDecision
from governai.policies.base import PolicyFunc, run_policy
from governai.workflows.exceptions import PolicyDeniedError


class PolicyEngine:
    def __init__(self) -> None:
        """Initialize PolicyEngine."""
        self._global: list[tuple[str, PolicyFunc]] = []
        self._workflow: dict[str, list[tuple[str, PolicyFunc]]] = {}

    def register(self, policy_func: PolicyFunc, *, workflow_name: str | None = None, name: str | None = None) -> None:
        """Register."""
        policy_name = name or getattr(policy_func, "__policy_name__", policy_func.__name__)
        if workflow_name is None:
            self._global.append((policy_name, policy_func))
            return
        self._workflow.setdefault(workflow_name, []).append((policy_name, policy_func))

    def policies_for(self, workflow_name: str) -> list[tuple[str, PolicyFunc]]:
        """Policies for."""
        return [*self._global, *self._workflow.get(workflow_name, [])]

    async def evaluate(
        self,
        *,
        workflow_name: str,
        ctx: PolicyContext,
    ) -> list[tuple[str, PolicyDecision]]:
        """Evaluate."""
        results: list[tuple[str, PolicyDecision]] = []
        for policy_name, policy_func in self.policies_for(workflow_name):
            decision = await run_policy(policy_func, ctx)
            results.append((policy_name, decision))
            if not decision.allow:
                raise PolicyDeniedError(decision.reason or f"Policy denied: {policy_name}")
        return results
