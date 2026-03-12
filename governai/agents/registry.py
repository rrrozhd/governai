from __future__ import annotations

from governai.agents.base import Agent


class AgentRegistry:
    def __init__(self) -> None:
        """Initialize AgentRegistry."""
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        """Register."""
        if agent.name in self._agents:
            raise ValueError(f"Agent already registered: {agent.name}")
        self._agents[agent.name] = agent

    def get(self, name: str) -> Agent:
        """Get."""
        try:
            return self._agents[name]
        except KeyError as exc:
            raise KeyError(f"Unknown agent: {name}") from exc

    def has(self, name: str) -> bool:
        """Has."""
        return name in self._agents

    def list(self) -> list[Agent]:
        """List."""
        return list(self._agents.values())
