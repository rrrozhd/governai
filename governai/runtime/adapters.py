from __future__ import annotations

from typing import Any, Protocol


class Executable(Protocol):
    name: str
    description: str
    capabilities: list[str]
    side_effect: bool
    requires_approval: bool
    executor_type: str

    async def execute(self, ctx: Any, data: Any) -> Any:  # pragma: no cover - protocol
        """Execute."""
        ...
