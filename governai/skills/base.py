from __future__ import annotations

from governai.tools.base import Tool


class Skill:
    def __init__(
        self,
        *,
        name: str,
        tools: list[Tool],
        description: str = "",
        version: str = "0.2.2",
    ) -> None:
        """Initialize Skill."""
        self.name = name
        self.description = description
        self.version = version
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"Duplicate tool name in skill {name}: {tool.name}")
            self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Tool:
        """Get tool."""
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool in skill {self.name}: {name}") from exc

    def list_tools(self) -> list[Tool]:
        """List tools."""
        return list(self._tools.values())
