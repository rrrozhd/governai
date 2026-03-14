from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError, model_validator

from governai.integrations.http_client import GovernedHTTPClient, GovernedHTTPError


class RemoteExecutionError(RuntimeError):
    """Raised when remote execution transport or payload handling fails."""

    def __init__(self, message: str, *, code: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class RemoteExecutionFailure(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class RemoteToolExecutionRequest(BaseModel):
    run_id: str
    workflow_name: str
    step_name: str
    executor_name: str
    executor_type: Literal["python", "cli"]
    input_payload: dict[str, Any]
    artifacts: dict[str, Any] = Field(default_factory=dict)
    channels: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    tool_kind: Literal["python", "cli"]
    command: list[str] | None = None
    timeout_seconds: float | None = None
    capabilities: list[str] = Field(default_factory=list)
    side_effect: bool = False
    requires_approval: bool = False


class RemoteToolCallRequest(BaseModel):
    tool_name: str
    payload: dict[str, Any]


class RemoteToolExecutionResponse(BaseModel):
    output_payload: dict[str, Any] | None = None
    error: RemoteExecutionFailure | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "RemoteToolExecutionResponse":
        """Ensure successful responses include payload and failed responses include error."""
        if self.error is None and self.output_payload is None:
            raise ValueError("successful remote tool response requires output_payload")
        if self.error is not None and self.output_payload is not None:
            raise ValueError("remote tool response cannot contain both output_payload and error")
        return self


class RemoteAgentExecutionRequest(BaseModel):
    run_id: str
    workflow_name: str
    step_name: str
    executor_name: str
    executor_type: Literal["agent"] = "agent"
    input_payload: dict[str, Any]
    artifacts: dict[str, Any] = Field(default_factory=dict)
    channels: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    instruction: str
    allowed_tools: list[str] = Field(default_factory=list)
    allowed_handoffs: list[str] = Field(default_factory=list)
    max_tool_calls: int = 1
    tool_calls_used: int = 0
    resume_tool_name: str | None = None
    resume_tool_result: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_resume_fields(self) -> "RemoteAgentExecutionRequest":
        """Require tool name/result pairs for resumed remote agent execution."""
        if (self.resume_tool_name is None) != (self.resume_tool_result is None):
            raise ValueError("resume_tool_name and resume_tool_result must be provided together")
        return self


class RemoteAgentExecutionResponse(BaseModel):
    status: Literal["final", "handoff", "needs_approval", "failed", "tool_call"]
    output_payload: dict[str, Any] | None = None
    next_agent: str | None = None
    reason: str | None = None
    requested_tool_call: RemoteToolCallRequest | None = None
    error: RemoteExecutionFailure | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "RemoteAgentExecutionResponse":
        """Normalize response invariants for remote agent execution."""
        if self.error is not None and self.status != "failed":
            raise ValueError("remote agent error payload requires failed status")
        if self.status == "final" and self.output_payload is None:
            raise ValueError("final remote agent response requires output_payload")
        if self.status == "handoff" and not self.next_agent:
            raise ValueError("handoff remote agent response requires next_agent")
        if self.status in {"failed", "needs_approval"} and not self.reason and self.error is None:
            raise ValueError(f"{self.status} remote agent response requires reason")
        if self.status == "tool_call" and self.requested_tool_call is None:
            raise ValueError("tool_call remote agent response requires requested_tool_call")
        return self


class RemoteExecutionAdapter(Protocol):
    """Typed boundary for contained remote execution."""

    async def execute_tool(self, request: RemoteToolExecutionRequest) -> RemoteToolExecutionResponse:
        """Execute one remote tool and return normalized payload."""

    async def execute_agent(self, request: RemoteAgentExecutionRequest) -> RemoteAgentExecutionResponse:
        """Execute one remote agent turn and return normalized payload."""

    async def health(self) -> dict[str, Any]:
        """Return adapter health metadata."""


class RemoteCheckpointAdapter(Protocol):
    """Extension boundary for remote checkpoint storage/restore providers."""

    async def write_checkpoint(self, payload: dict[str, Any]) -> str:
        """Persist checkpoint payload and return checkpoint id."""

    async def load_checkpoint(self, checkpoint_id: str) -> dict[str, Any] | None:
        """Load checkpoint payload by id."""


class RemoteExecutionFactory(Protocol):
    """Factory boundary for remote/distributed backend package."""

    def create_execution_adapter(self) -> RemoteExecutionAdapter:
        """Create remote task execution adapter."""

    def create_checkpoint_adapter(self) -> RemoteCheckpointAdapter:
        """Create remote checkpoint adapter."""


@dataclass
class HTTPSandboxExecutionAdapter:
    """HTTP/JSON adapter for contained remote execution."""

    base_url: str
    bearer_token: str
    http_client: GovernedHTTPClient = field(default_factory=GovernedHTTPClient)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if not self.base_url:
            raise ValueError("base_url must not be empty")
        if not self.bearer_token:
            raise ValueError("bearer_token must not be empty")
        if not isinstance(self.http_client, GovernedHTTPClient):
            self.http_client = GovernedHTTPClient()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.bearer_token}"}

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            response = await self.http_client.request(
                method="POST",
                url=url,
                json_body=payload,
                headers=self._headers(),
                accept_status={200},
            )
        except GovernedHTTPError as exc:
            raise RemoteExecutionError(
                f"Sandbox HTTP request failed for {path}: {exc}",
                code="http_error",
                details={"status_code": exc.status_code, "body": exc.body},
            ) from exc
        try:
            data = response.json()
        except Exception as exc:
            raise RemoteExecutionError(
                f"Sandbox returned invalid JSON for {path}",
                code="invalid_json",
                details={"body": response.text()},
            ) from exc
        if not isinstance(data, dict):
            raise RemoteExecutionError(
                f"Sandbox returned non-object JSON for {path}",
                code="invalid_payload",
                details={"body": data},
            )
        return data

    async def execute_tool(self, request: RemoteToolExecutionRequest) -> RemoteToolExecutionResponse:
        payload = await self._post_json("/execute/tool", request.model_dump(mode="json"))
        try:
            return RemoteToolExecutionResponse.model_validate(payload)
        except ValidationError as exc:
            raise RemoteExecutionError(
                "Sandbox tool response failed validation",
                code="invalid_tool_response",
                details={"errors": exc.errors()},
            ) from exc

    async def execute_agent(self, request: RemoteAgentExecutionRequest) -> RemoteAgentExecutionResponse:
        payload = await self._post_json("/execute/agent", request.model_dump(mode="json"))
        try:
            return RemoteAgentExecutionResponse.model_validate(payload)
        except ValidationError as exc:
            raise RemoteExecutionError(
                "Sandbox agent response failed validation",
                code="invalid_agent_response",
                details={"errors": exc.errors()},
            ) from exc

    async def health(self) -> dict[str, Any]:
        url = f"{self.base_url}/health"
        try:
            response = await self.http_client.request(
                method="GET",
                url=url,
                headers=self._headers(),
                accept_status={200},
            )
        except GovernedHTTPError as exc:
            raise RemoteExecutionError(
                f"Sandbox health check failed: {exc}",
                code="http_error",
                details={"status_code": exc.status_code, "body": exc.body},
            ) from exc
        try:
            payload = response.json()
        except Exception as exc:
            raise RemoteExecutionError(
                "Sandbox health response failed JSON decoding",
                code="invalid_json",
                details={"body": response.text()},
            ) from exc
        if not isinstance(payload, dict):
            raise RemoteExecutionError(
                "Sandbox health response must be an object",
                code="invalid_payload",
                details={"body": payload},
            )
        return payload
