from __future__ import annotations

from governai.audit.emitter import AuditEmitter
from governai.models.audit import AuditEvent


class InMemoryAuditEmitter(AuditEmitter):
    def __init__(self) -> None:
        """Initialize InMemoryAuditEmitter."""
        self.events: list[AuditEvent] = []

    async def emit(self, event: AuditEvent) -> None:
        """Emit."""
        self.events.append(event)
