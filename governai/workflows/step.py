from __future__ import annotations

from copy import deepcopy
from typing import Any

from governai.models.common import DeterminismMode, END_STEP
from governai.workflows.transitions import (
    BoundedRoutingTransition,
    RuleBasedTransition,
    StrictTransition,
    TransitionConfig,
)


class StepDefinition:
    def __init__(
        self,
        name: str,
        *,
        tool: Any = None,
        agent: Any = None,
        required_artifacts: list[str] | None = None,
        emitted_artifact: str | None = None,
        approval_override: bool | None = None,
    ) -> None:
        """Initialize StepDefinition."""
        if (tool is None) == (agent is None):
            raise ValueError("Step must have exactly one of tool or agent")
        self.name = name
        self.tool = tool
        self.agent = agent
        self.required_artifacts = required_artifacts or []
        self.emitted_artifact = emitted_artifact
        self.approval_override = approval_override
        self.transition: TransitionConfig | None = None
        self.determinism_mode: DeterminismMode | None = None

    @property
    def executor(self) -> Any:
        """Executor."""
        return self.tool if self.tool is not None else self.agent

    def then(self, next_step: str) -> "StepDefinition":
        """Then."""
        self.transition = StrictTransition(next_step=next_step)
        self.determinism_mode = DeterminismMode.STRICT
        return self

    def then_end(self) -> "StepDefinition":
        """Then end."""
        self.transition = StrictTransition(next_step=END_STEP)
        self.determinism_mode = DeterminismMode.STRICT
        return self

    def branch(self, *, router: str, mapping: dict[str, str]) -> "StepDefinition":
        """Branch."""
        self.transition = RuleBasedTransition(router=router, mapping=mapping)
        self.determinism_mode = DeterminismMode.RULE_BASED
        return self

    def route_to(self, *, allowed: list[str]) -> "StepDefinition":
        """Route to."""
        self.transition = BoundedRoutingTransition(allowed=allowed)
        self.determinism_mode = DeterminismMode.BOUNDED_ROUTING
        return self

    def copy(self) -> "StepDefinition":
        """Copy."""
        step = StepDefinition(
            self.name,
            tool=self.tool,
            agent=self.agent,
            required_artifacts=list(self.required_artifacts),
            emitted_artifact=self.emitted_artifact,
            approval_override=self.approval_override,
        )
        step.transition = deepcopy(self.transition)
        step.determinism_mode = self.determinism_mode
        return step
