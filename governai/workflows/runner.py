from __future__ import annotations

from typing import Any

from governai.models.common import DeterminismMode, END_STEP
from governai.workflows.exceptions import (
    BranchResolutionError,
    IllegalTransitionError,
    RoutingResolutionError,
)
from governai.workflows.step import StepDefinition
from governai.workflows.transitions import (
    BoundedRoutingTransition,
    RuleBasedTransition,
    StrictTransition,
)


def resolve_next_step(
    *,
    step: StepDefinition,
    output_payload: dict[str, Any],
    steps: dict[str, StepDefinition],
    handoff_agent: str | None = None,
) -> str:
    """Resolve next step."""
    transition = step.transition
    if transition is None or step.determinism_mode is None:
        raise IllegalTransitionError(f"Step {step.name} has no transition configured")

    next_step: str
    if step.determinism_mode == DeterminismMode.STRICT:
        assert isinstance(transition, StrictTransition)
        next_step = transition.next_step
    elif step.determinism_mode == DeterminismMode.RULE_BASED:
        assert isinstance(transition, RuleBasedTransition)
        route_value = output_payload.get(transition.router)
        if route_value is None:
            raise BranchResolutionError(
                f"Step {step.name} missing router field '{transition.router}'"
            )
        mapped = transition.mapping.get(str(route_value))
        if mapped is None:
            raise BranchResolutionError(
                f"Step {step.name} has no branch mapping for value '{route_value}'"
            )
        next_step = mapped
    else:
        assert isinstance(transition, BoundedRoutingTransition)
        proposed = output_payload.get("next_step")
        if not isinstance(proposed, str):
            raise RoutingResolutionError(
                f"Step {step.name} requires 'next_step' string for bounded routing"
            )
        if proposed.lower() == "end":
            proposed = END_STEP
        if proposed not in transition.allowed:
            raise RoutingResolutionError(
                f"Step {step.name} proposed illegal next step '{proposed}'"
            )
        next_step = proposed

    if next_step != END_STEP and next_step not in steps:
        raise IllegalTransitionError(f"Step {step.name} resolved unknown next step {next_step}")

    if handoff_agent is not None:
        if next_step == END_STEP:
            raise IllegalTransitionError(
                f"Agent step {step.name} proposed handoff to {handoff_agent} but transition ended"
            )
        candidate = steps[next_step]
        if candidate.agent is None or candidate.agent.name != handoff_agent:
            raise IllegalTransitionError(
                f"Agent handoff target {handoff_agent} does not match workflow next step {next_step}"
            )

    return next_step
