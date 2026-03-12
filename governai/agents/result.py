from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class AgentTask(BaseModel):
    task_id: str
    goal: str
    input_payload: dict[str, Any]
    context_artifacts: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    status: Literal["final", "handoff", "needs_approval", "failed"]
    output_payload: dict[str, Any] | None = None
    next_agent: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_result(self) -> "AgentResult":
        """Validate result."""
        if self.status == "handoff" and not self.next_agent:
            raise ValueError("handoff status requires next_agent")
        if self.status == "final" and self.output_payload is None:
            raise ValueError("final status requires output_payload")
        if self.status in {"failed", "needs_approval"} and not self.reason:
            raise ValueError(f"{self.status} status requires reason")
        return self
