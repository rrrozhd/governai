from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ValidationError


InModelT = TypeVar("InModelT", bound=BaseModel)
OutModelT = TypeVar("OutModelT", bound=BaseModel)
ExecutionPlacement = Literal["local_only", "remote_only", "local_or_remote"]


class ToolError(Exception):
    """Base tool error."""


class ToolValidationError(ToolError):
    """Raised when input or output validation fails."""


class ToolExecutionError(ToolError):
    """Raised when tool execution fails."""


class CLIToolError(ToolExecutionError):
    """Base CLI tool error."""


class CLIToolProcessError(CLIToolError):
    def __init__(self, message: str, *, exit_code: int, stderr: str, stdout: str) -> None:
        """Initialize CLIToolProcessError."""
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr
        self.stdout = stdout


class CLIToolOutputError(CLIToolError):
    """Raised when CLI output is invalid."""


class CLIToolTimeoutError(CLIToolError):
    """Raised when CLI execution times out."""


class Tool(Generic[InModelT, OutModelT]):
    def __init__(
        self,
        *,
        name: str,
        description: str = "",
        input_model: type[InModelT],
        output_model: type[OutModelT],
        capabilities: list[str] | None = None,
        side_effect: bool = False,
        timeout_seconds: float | None = None,
        requires_approval: bool = False,
        tags: list[str] | None = None,
        executor_type: str = "python",
        execution_placement: ExecutionPlacement = "local_only",
        remote_name: str | None = None,
    ) -> None:
        """Initialize Tool."""
        self.name = name
        self.description = description
        self.input_model = input_model
        self.output_model = output_model
        self.capabilities = capabilities or []
        self.side_effect = side_effect
        self.timeout_seconds = timeout_seconds
        self.requires_approval = requires_approval
        self.tags = tags or []
        self.executor_type = executor_type
        self.execution_placement = execution_placement
        self.remote_name = remote_name or name

    async def execute(self, ctx: Any, data: Any) -> OutModelT:
        """Execute."""
        try:
            validated_input = self.input_model.model_validate(data)
        except ValidationError as exc:
            raise ToolValidationError(f"Input validation failed for {self.name}: {exc}") from exc

        try:
            output = await self._execute_validated(ctx, validated_input)
        except ToolError:
            raise
        except Exception as exc:  # pragma: no cover - defensive wrapper
            raise ToolExecutionError(f"Execution failed for {self.name}: {exc}") from exc

        try:
            return self.output_model.model_validate(output)
        except ValidationError as exc:
            raise ToolValidationError(f"Output validation failed for {self.name}: {exc}") from exc

    async def _execute_validated(self, ctx: Any, data: InModelT) -> Any:  # pragma: no cover - abstract
        """Internal helper to execute validated."""
        raise NotImplementedError

    @classmethod
    def from_cli(
        cls,
        *,
        name: str,
        command: list[str],
        input_model: type[InModelT],
        output_model: type[OutModelT],
        input_mode: str = "json-stdin",
        output_mode: str = "json-stdout",
        description: str = "",
        capabilities: list[str] | None = None,
        side_effect: bool = False,
        timeout_seconds: float | None = None,
        requires_approval: bool = False,
        tags: list[str] | None = None,
        execution_placement: ExecutionPlacement = "local_only",
        remote_name: str | None = None,
    ) -> "Tool[InModelT, OutModelT]":
        """From cli."""
        from governai.tools.cli_tool import CLITool

        return CLITool(
            name=name,
            command=command,
            input_model=input_model,
            output_model=output_model,
            input_mode=input_mode,
            output_mode=output_mode,
            description=description,
            capabilities=capabilities,
            side_effect=side_effect,
            timeout_seconds=timeout_seconds,
            requires_approval=requires_approval,
            tags=tags,
            execution_placement=execution_placement,
            remote_name=remote_name,
        )
