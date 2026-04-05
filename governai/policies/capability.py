from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from governai.models.policy import PolicyContext, PolicyDecision

GrantScope = Literal["global", "workflow", "step"]


class CapabilityGrant(BaseModel):
    """A single capability grant with three-tier scoping.

    Scoping rules:
    - scope="global": grant applies to all workflows and steps.
    - scope="workflow": grant applies only when ctx.workflow_name == target.
    - scope="step": grant applies only when ctx.step_name == target.

    For scope="workflow", target must be the workflow name matching ctx.workflow_name.
    For scope="step", target must be the bare step name matching ctx.step_name.
    """

    capability: str
    scope: GrantScope = "global"
    target: str | None = None  # workflow_name for scope="workflow", step_name for scope="step"


def make_capability_policy(grants: list[CapabilityGrant]):
    """Return a PolicyFunc that checks required capabilities against provided grants.

    Per D-01: Runs inside PolicyEngine.evaluate() like any other policy.
    Per D-02: Three-tier scoping (global, workflow, step).
    Per D-03: Grants provided via constructor injection to LocalRuntime.
    Per D-04: Deny lists missing, required, and granted capabilities.
    """

    def capability_policy(ctx: PolicyContext) -> PolicyDecision:
        if not ctx.capabilities:
            return PolicyDecision(allow=True)

        granted: set[str] = set()
        for grant in grants:
            if grant.scope == "global":
                granted.add(grant.capability)
            elif grant.scope == "workflow" and grant.target == ctx.workflow_name:
                granted.add(grant.capability)
            elif grant.scope == "step" and grant.target == ctx.step_name:
                granted.add(grant.capability)

        required = set(ctx.capabilities)
        missing = required - granted
        if missing:
            missing_str = ", ".join(sorted(missing))
            required_str = ", ".join(sorted(required))
            granted_str = ", ".join(sorted(granted))
            return PolicyDecision(
                allow=False,
                reason=f"Missing capability: {missing_str}. Required: [{required_str}]. Granted: [{granted_str}].",
            )
        return PolicyDecision(allow=True)

    capability_policy.__name__ = "capability_policy"
    return capability_policy
