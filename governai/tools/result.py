from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    tool_name: str
    executor_type: str
    output: dict[str, Any] = Field(default_factory=dict)
