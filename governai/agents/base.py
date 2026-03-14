from __future__ import annotations

import inspect
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Union

from pydantic import BaseModel, ValidationError

from governai.agents.context import AgentExecutionContext
from governai.agents.exceptions import AgentExecutionError
from governai.agents.result import AgentResult, AgentTask
from governai.tools.base import ExecutionPlacement

AgentReturn = Union[AgentResult, dict[str, Any]]
AgentHandler = Callable[[AgentExecutionContext, AgentTask], Union[Awaitable[AgentReturn], AgentReturn]]


class Agent:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        instruction: str,
        handler: AgentHandler,
        input_model: type[BaseModel],
        output_model: type[BaseModel],
        allowed_tools: list[str],
        allowed_handoffs: list[str],
        max_turns: int = 1,
        max_tool_calls: int = 1,
        tags: list[str] | None = None,
        requires_approval: bool = False,
        capabilities: list[str] | None = None,
        side_effect: bool = False,
        execution_placement: ExecutionPlacement = "local_only",
        remote_name: str | None = None,
    ) -> None:
        """Initialize Agent."""
        if max_turns < 1:
            raise ValueError("max_turns must be >= 1")
        if max_tool_calls < 0:
            raise ValueError("max_tool_calls must be >= 0")
        self.name = name
        self.description = description
        self.instruction = instruction
        self.handler = handler
        self.input_model = input_model
        self.output_model = output_model
        self.allowed_tools = allowed_tools
        self.allowed_handoffs = allowed_handoffs
        self.max_turns = max_turns
        self.max_tool_calls = max_tool_calls
        self.tags = tags or []
        self.requires_approval = requires_approval
        self.capabilities = capabilities or []
        self.side_effect = side_effect
        self.executor_type = "agent"
        self.execution_placement = execution_placement
        self.remote_name = remote_name or name

    async def execute(self, ctx: AgentExecutionContext, data: Any) -> AgentResult:
        """Execute."""
        try:
            validated_input = self.input_model.model_validate(data)
        except ValidationError as exc:
            raise AgentExecutionError(f"Agent input validation failed for {self.name}: {exc}") from exc

        task = AgentTask(
            task_id=str(uuid.uuid4()),
            goal=self.instruction,
            input_payload=validated_input.model_dump(mode="json"),
            context_artifacts=ctx.artifacts_snapshot(),
        )
        result_raw = self.handler(ctx, task)
        if inspect.isawaitable(result_raw):
            result_raw = await result_raw

        try:
            result = AgentResult.model_validate(result_raw)
        except ValidationError as exc:
            raise AgentExecutionError(f"Agent returned invalid AgentResult for {self.name}: {exc}") from exc

        if result.status == "final":
            try:
                validated_output = self.output_model.model_validate(result.output_payload)
            except ValidationError as exc:
                raise AgentExecutionError(
                    f"Agent output validation failed for {self.name}: {exc}"
                ) from exc
            result.output_payload = validated_output.model_dump(mode="json")

        if result.status == "handoff" and result.next_agent not in self.allowed_handoffs:
            raise AgentExecutionError(
                f"Agent {self.name} attempted disallowed handoff to {result.next_agent}"
            )

        if ctx.tool_calls_used > self.max_tool_calls:
            raise AgentExecutionError(
                f"Agent {self.name} exceeded max_tool_calls={self.max_tool_calls}"
            )

        return result
