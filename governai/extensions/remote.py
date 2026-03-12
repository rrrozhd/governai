from __future__ import annotations

from typing import Any, Protocol


class RemoteExecutionAdapter(Protocol):
    """Extension boundary for future distributed execution backends."""

    async def call(self, task_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute one remote task and return normalized payload."""

    async def health(self) -> dict[str, Any]:
        """Return adapter health metadata."""


class RemoteCheckpointAdapter(Protocol):
    """Extension boundary for remote checkpoint storage/restore providers."""

    async def write_checkpoint(self, payload: dict[str, Any]) -> str:
        """Persist checkpoint payload and return checkpoint id."""

    async def load_checkpoint(self, checkpoint_id: str) -> dict[str, Any] | None:
        """Load checkpoint payload by id."""


class RemoteExecutionFactory(Protocol):
    """Factory boundary for future remote/distributed backend package."""

    def create_execution_adapter(self) -> RemoteExecutionAdapter:
        """Create remote task execution adapter."""

    def create_checkpoint_adapter(self) -> RemoteCheckpointAdapter:
        """Create remote checkpoint adapter."""
