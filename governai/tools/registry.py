from __future__ import annotations

from governai.tools.base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        """Initialize ToolRegistry."""
        self._tools: dict[str, Tool] = {}
        self._tools_by_remote_name: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register."""
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        if tool.remote_name in self._tools_by_remote_name:
            raise ValueError(f"Tool remote_name already registered: {tool.remote_name}")
        self._tools[tool.name] = tool
        self._tools_by_remote_name[tool.remote_name] = tool

    def get(self, name: str) -> Tool:
        """Get."""
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def has(self, name: str) -> bool:
        """Has."""
        return name in self._tools

    def get_remote(self, remote_name: str) -> Tool:
        """Get by remote name."""
        try:
            return self._tools_by_remote_name[remote_name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool remote_name: {remote_name}") from exc

    def has_remote(self, remote_name: str) -> bool:
        """Has by remote name."""
        return remote_name in self._tools_by_remote_name

    def list(self) -> list[Tool]:
        """List."""
        return list(self._tools.values())
