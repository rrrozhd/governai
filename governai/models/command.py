from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class InterruptInstruction(BaseModel):
    message: str
    context: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: int | None = None


class Command(BaseModel):
    """Runtime control command returned by step executors."""

    goto: str | None = None
    state_update: dict[str, Any] = Field(default_factory=dict)
    interrupt: InterruptInstruction | None = None
    output: Any = None

    def has_interrupt(self) -> bool:
        """Has interrupt."""
        return self.interrupt is not None

