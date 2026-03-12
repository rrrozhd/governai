from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PolicyContext(BaseModel):
    workflow_name: str
    step_name: str
    tool_name: str
    capabilities: list[str] = Field(default_factory=list)
    side_effect: bool = False
    artifacts: dict[str, Any] = Field(default_factory=dict)
    pending_approval: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyDecision(BaseModel):
    allow: bool
    reason: str | None = None
    requires_approval: bool = False
