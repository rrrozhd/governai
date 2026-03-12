from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any

from governai.models.audit import AuditEvent
from governai.models.common import EventType


class AuditEmitter(ABC):
    @abstractmethod
    async def emit(self, event: AuditEvent) -> None:
        """Emit."""
        raise NotImplementedError


async def emit_event(
    emitter: AuditEmitter,
    *,
    run_id: str,
    workflow_name: str,
    event_type: EventType,
    step_name: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    """Emit event."""
    event = AuditEvent(
        event_id=str(uuid.uuid4()),
        run_id=run_id,
        workflow_name=workflow_name,
        step_name=step_name,
        event_type=event_type,
        payload=payload or {},
    )
    await emitter.emit(event)
    return event
