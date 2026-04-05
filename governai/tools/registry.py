from __future__ import annotations

import hashlib
import json

from governai.tools.base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        """Initialize ToolRegistry."""
        self._tools: dict[tuple[str, str], Tool] = {}
        self._tools_by_remote_name: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register."""
        key = (tool.name, tool.version)
        if key in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}@{tool.version}")
        if tool.remote_name in self._tools_by_remote_name:
            raise ValueError(f"Tool remote_name already registered: {tool.remote_name}")
        # Compute schema fingerprint (blake2b, 16-byte digest -> 32-char hex)
        input_schema = tool.input_model.model_json_schema()
        output_schema = tool.output_model.model_json_schema()
        combined = json.dumps(
            {"input": input_schema, "output": output_schema},
            sort_keys=True,
        ).encode()
        tool.schema_fingerprint = hashlib.blake2b(combined, digest_size=16).hexdigest()
        self._tools[key] = tool
        self._tools_by_remote_name[tool.remote_name] = tool

    def get(self, name: str, version: str = "0.0.0") -> Tool:
        """Get."""
        try:
            return self._tools[(name, version)]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}@{version}") from exc

    def has(self, name: str, version: str = "0.0.0") -> bool:
        """Has."""
        return (name, version) in self._tools

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
