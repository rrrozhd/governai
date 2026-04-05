from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ThreadStatus(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    INTERRUPTED = "interrupted"
    IDLE = "idle"
    ARCHIVED = "archived"


ALLOWED_THREAD_TRANSITIONS: dict[ThreadStatus, set[ThreadStatus]] = {
    ThreadStatus.CREATED: {ThreadStatus.ACTIVE},
    ThreadStatus.ACTIVE: {ThreadStatus.IDLE, ThreadStatus.INTERRUPTED},
    ThreadStatus.INTERRUPTED: {ThreadStatus.ACTIVE},
    ThreadStatus.IDLE: {ThreadStatus.ACTIVE, ThreadStatus.ARCHIVED},
    ThreadStatus.ARCHIVED: set(),
}


class ThreadTransitionError(ValueError):
    """Raised when a thread state transition is invalid."""


class ThreadRecord(BaseModel):
    thread_id: str
    status: ThreadStatus = ThreadStatus.CREATED
    run_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ThreadStore(ABC):
    """Persistence backend for thread lifecycle records."""

    @abstractmethod
    async def create(self, thread_id: str) -> ThreadRecord:
        """Create a new thread record in CREATED state."""

    @abstractmethod
    async def get(self, thread_id: str) -> ThreadRecord | None:
        """Fetch a thread record by ID, or None if not found."""

    @abstractmethod
    async def transition(self, thread_id: str, new_status: ThreadStatus) -> ThreadRecord:
        """Transition thread to new status. Raises ThreadTransitionError if invalid, KeyError if not found."""

    @abstractmethod
    async def add_run_id(self, thread_id: str, run_id: str) -> ThreadRecord:
        """Associate a run with this thread. Raises KeyError if not found."""

    @abstractmethod
    async def archive(self, thread_id: str) -> ThreadRecord:
        """Archive a thread (status transition to ARCHIVED). Raises ThreadTransitionError if invalid."""


class InMemoryThreadStore(ThreadStore):
    def __init__(self) -> None:
        self._records: dict[str, ThreadRecord] = {}

    async def create(self, thread_id: str) -> ThreadRecord:
        if thread_id in self._records:
            raise KeyError(f"Thread already exists: {thread_id}")
        record = ThreadRecord(thread_id=thread_id)
        self._records[thread_id] = record
        return record.model_copy(deep=True)

    async def get(self, thread_id: str) -> ThreadRecord | None:
        record = self._records.get(thread_id)
        return record.model_copy(deep=True) if record else None

    async def transition(self, thread_id: str, new_status: ThreadStatus) -> ThreadRecord:
        record = self._records.get(thread_id)
        if record is None:
            raise KeyError(f"Unknown thread_id: {thread_id}")
        allowed = ALLOWED_THREAD_TRANSITIONS[record.status]
        if new_status not in allowed:
            raise ThreadTransitionError(
                f"Invalid transition for thread {thread_id}: {record.status.value} -> {new_status.value}"
            )
        record.status = new_status
        record.updated_at = _utcnow()
        return record.model_copy(deep=True)

    async def add_run_id(self, thread_id: str, run_id: str) -> ThreadRecord:
        record = self._records.get(thread_id)
        if record is None:
            raise KeyError(f"Unknown thread_id: {thread_id}")
        record.run_ids.append(run_id)
        record.updated_at = _utcnow()
        return record.model_copy(deep=True)

    async def archive(self, thread_id: str) -> ThreadRecord:
        return await self.transition(thread_id, ThreadStatus.ARCHIVED)
