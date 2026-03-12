from __future__ import annotations

from governai.tools.base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        """Initialize ToolRegistry."""
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register."""
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        """Get."""
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def has(self, name: str) -> bool:
        """Has."""
        return name in self._tools

    def list(self) -> list[Tool]:
        """List."""
        return list(self._tools.values())
