from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Artifacts(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Get."""
        return self.values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set."""
        self.values[key] = value

    def has(self, key: str) -> bool:
        """Has."""
        return key in self.values
