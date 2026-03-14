from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from governai.models.common import EventType


def _utcnow() -> datetime:
    """Internal helper to utcnow."""
    return datetime.now(timezone.utc)


class AuditEvent(BaseModel):
    event_id: str
    timestamp: datetime = Field(default_factory=_utcnow)
    run_id: str
    thread_id: str | None = None
    workflow_name: str
    step_name: str | None = None
    event_type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
