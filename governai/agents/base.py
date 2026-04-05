from __future__ import annotations

import hashlib
import inspect
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Union

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

    def to_spec(self) -> "AgentSpec":
        """Extract a serializable AgentSpec from this live Agent instance."""
        from governai.agents.spec import AgentSpec, ModelSchemaRef

        input_schema = self.input_model.model_json_schema()
        output_schema = self.output_model.model_json_schema()
        combined = json.dumps(
            {"input": input_schema, "output": output_schema}, sort_keys=True
        ).encode()
        fingerprint = hashlib.blake2b(combined, digest_size=16).hexdigest()

        return AgentSpec(
            name=self.name,
            description=self.description,
            instruction=self.instruction,
            version=getattr(self, "version", "0.0.0"),
            schema_fingerprint=fingerprint,
            input_model=ModelSchemaRef(
                name=self.input_model.__name__, schema=input_schema
            ),
            output_model=ModelSchemaRef(
                name=self.output_model.__name__, schema=output_schema
            ),
            allowed_tools=list(self.allowed_tools),
            allowed_handoffs=list(self.allowed_handoffs),
            max_turns=self.max_turns,
            max_tool_calls=self.max_tool_calls,
            tags=list(self.tags),
            requires_approval=self.requires_approval,
            capabilities=list(self.capabilities),
            side_effect=self.side_effect,
            executor_type=self.executor_type,
            execution_placement=self.execution_placement,
            remote_name=self.remote_name,
        )

    @classmethod
    def from_spec(
        cls,
        spec: "AgentSpec",
        handler: AgentHandler,
        registry: Any = None,
    ) -> "Agent":
        """Reconstruct an Agent from an AgentSpec, handler, and model registry.

        Args:
            spec: The serializable agent descriptor.
            handler: The callable agent handler.
            registry: A ModelRegistry instance for resolving model classes by name.

        Raises:
            ValueError: If registry is None (required to resolve model classes).
        """
        if registry is None:
            raise ValueError(
                f"ModelRegistry required to reconstruct input/output models "
                f"for Agent '{spec.name}'"
            )

        input_model = registry.resolve(spec.input_model.name)
        output_model = registry.resolve(spec.output_model.name)

        return cls(
            name=spec.name,
            description=spec.description,
            instruction=spec.instruction,
            handler=handler,
            input_model=input_model,
            output_model=output_model,
            allowed_tools=spec.allowed_tools,
            allowed_handoffs=spec.allowed_handoffs,
            max_turns=spec.max_turns,
            max_tool_calls=spec.max_tool_calls,
            tags=spec.tags,
            requires_approval=spec.requires_approval,
            capabilities=spec.capabilities,
            side_effect=spec.side_effect,
            execution_placement=spec.execution_placement,
            remote_name=spec.remote_name,
        )
