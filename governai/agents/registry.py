from __future__ import annotations

from governai.agents.base import Agent


class AgentRegistry:
    def __init__(self) -> None:
        """Initialize AgentRegistry."""
        self._agents: dict[str, Agent] = {}
        self._agents_by_remote_name: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        """Register."""
        if agent.name in self._agents:
            raise ValueError(f"Agent already registered: {agent.name}")
        if agent.remote_name in self._agents_by_remote_name:
            raise ValueError(f"Agent remote_name already registered: {agent.remote_name}")
        self._agents[agent.name] = agent
        self._agents_by_remote_name[agent.remote_name] = agent

    def get(self, name: str) -> Agent:
        """Get."""
        try:
            return self._agents[name]
        except KeyError as exc:
            raise KeyError(f"Unknown agent: {name}") from exc

    def has(self, name: str) -> bool:
        """Has."""
        return name in self._agents

    def get_remote(self, remote_name: str) -> Agent:
        """Get by remote name."""
        try:
            return self._agents_by_remote_name[remote_name]
        except KeyError as exc:
            raise KeyError(f"Unknown agent remote_name: {remote_name}") from exc

    def has_remote(self, remote_name: str) -> bool:
        """Has by remote name."""
        return remote_name in self._agents_by_remote_name

    def list(self) -> list[Agent]:
        """List."""
        return list(self._agents.values())
