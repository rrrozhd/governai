from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from governai.agents.exceptions import AgentLimitExceededError, AgentToolNotAllowedError
from governai.runtime.context import ExecutionContext


class AgentExecutionContext:
    def __init__(
        self,
        *,
        base_context: ExecutionContext,
        allowed_tools: list[str],
        max_tool_calls: int,
        tool_caller: Callable[[str, Any], Awaitable[dict[str, Any]]],
    ) -> None:
        """Initialize AgentExecutionContext."""
        self.run_id = base_context.run_id
        self.workflow_name = base_context.workflow_name
        self.step_name = base_context.step_name
        self.approval_request = base_context.approval_request
        self._base_context = base_context
        self._allowed_tools = set(allowed_tools)
        self._max_tool_calls = max_tool_calls
        self._tool_calls = 0
        self._tool_caller = tool_caller

    def get_artifact(self, key: str, default: Any = None) -> Any:
        """Get artifact."""
        return self._base_context.get_artifact(key, default)

    def artifacts_snapshot(self) -> dict[str, Any]:
        """Artifacts snapshot."""
        return self._base_context.artifacts_snapshot()

    def set_metadata(self, key: str, value: Any) -> None:
        """Set metadata."""
        self._base_context.set_metadata(key, value)

    @property
    def tool_calls_used(self) -> int:
        """Tool calls used."""
        return self._tool_calls

    async def use_tool(self, name: str, payload: Any) -> dict[str, Any]:
        """Use tool."""
        if name not in self._allowed_tools:
            raise AgentToolNotAllowedError(f"Agent step {self.step_name} cannot call tool {name}")
        if self._tool_calls >= self._max_tool_calls:
            raise AgentLimitExceededError(
                f"Agent step {self.step_name} exceeded max_tool_calls={self._max_tool_calls}"
            )
        self._tool_calls += 1
        return await self._tool_caller(name, payload)
