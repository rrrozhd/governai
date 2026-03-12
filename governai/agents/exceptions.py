from __future__ import annotations


class AgentError(Exception):
    """Base agent error."""


class AgentExecutionError(AgentError):
    """Raised when agent execution fails."""


class AgentToolNotAllowedError(AgentError):
    """Raised when agent attempts disallowed tool."""


class AgentHandoffError(AgentError):
    """Raised when handoff is invalid."""


class AgentLimitExceededError(AgentError):
    """Raised when bounded limits are exceeded."""
