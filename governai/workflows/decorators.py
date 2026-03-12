from __future__ import annotations

from typing import Any

from governai.workflows.step import StepDefinition


def step(
    name: str,
    *,
    tool: Any = None,
    agent: Any = None,
    required_artifacts: list[str] | None = None,
    emitted_artifact: str | None = None,
    approval_override: bool | None = None,
) -> StepDefinition:
    """Step."""
    return StepDefinition(
        name=name,
        tool=tool,
        agent=agent,
        required_artifacts=required_artifacts,
        emitted_artifact=emitted_artifact,
        approval_override=approval_override,
    )
