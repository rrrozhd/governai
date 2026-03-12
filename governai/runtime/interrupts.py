from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class InterruptRequest:
    interrupt_id: str
    run_id: str
    step_name: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)
    epoch: int = 0
    created_at: int = field(default_factory=lambda: int(time.time()))
    expires_at: int = 0
    status: str = "pending"


@dataclass
class InterruptResolution:
    request: InterruptRequest
    response: Any
    resolved_at: int = field(default_factory=lambda: int(time.time()))


class InterruptManager:
    """Tracks non-approval interrupts with TTL and epoch guards."""

    def __init__(self, *, default_ttl_seconds: int = 1800) -> None:
        """Initialize InterruptManager."""
        self.default_ttl_seconds = default_ttl_seconds
        self._requests: dict[str, dict[str, InterruptRequest]] = {}
        self._epochs: dict[str, int] = {}

    def current_epoch(self, run_id: str) -> int:
        """Current epoch."""
        return self._epochs.get(run_id, 0)

    def bump_epoch(self, run_id: str) -> int:
        """Bump epoch."""
        next_epoch = self.current_epoch(run_id) + 1
        self._epochs[run_id] = next_epoch
        return next_epoch

    def create(
        self,
        *,
        run_id: str,
        step_name: str,
        message: str,
        context: dict[str, Any] | None = None,
        ttl_seconds: int | None = None,
        epoch: int | None = None,
        max_pending: int | None = None,
    ) -> InterruptRequest:
        """Create."""
        if max_pending is not None and max_pending >= 0:
            current_pending = self.list_pending(run_id, epoch=epoch)
            if len(current_pending) >= max_pending:
                raise ValueError(
                    f"Run {run_id} reached max pending interrupts ({max_pending})"
                )
        now_ts = int(time.time())
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        resolved_epoch = self.current_epoch(run_id) if epoch is None else epoch
        request = InterruptRequest(
            interrupt_id=str(uuid.uuid4()),
            run_id=run_id,
            step_name=step_name,
            message=message,
            context=dict(context or {}),
            epoch=resolved_epoch,
            created_at=now_ts,
            expires_at=now_ts + int(ttl),
        )
        self._requests.setdefault(run_id, {})[request.interrupt_id] = request
        return request

    def list_pending(self, run_id: str, *, epoch: int | None = None) -> list[InterruptRequest]:
        """List pending."""
        now_ts = int(time.time())
        requests = self._requests.get(run_id, {})
        out: list[InterruptRequest] = []
        for req in requests.values():
            if req.status != "pending":
                continue
            if req.expires_at <= now_ts:
                req.status = "expired"
                continue
            if epoch is not None and req.epoch != epoch:
                continue
            out.append(req)
        out.sort(key=lambda item: (item.created_at, item.interrupt_id))
        return out

    def resolve(
        self,
        *,
        run_id: str,
        interrupt_id: str,
        response: Any,
        epoch: int | None = None,
    ) -> InterruptResolution:
        """Resolve."""
        requests = self._requests.get(run_id, {})
        req = requests.get(interrupt_id)
        if req is None:
            raise KeyError(f"Unknown interrupt_id: {interrupt_id}")
        if req.status != "pending":
            raise ValueError(f"Interrupt {interrupt_id} is not pending")
        if req.expires_at <= int(time.time()):
            req.status = "expired"
            raise ValueError(f"Interrupt {interrupt_id} has expired")
        if epoch is not None and req.epoch != epoch:
            raise ValueError(
                f"Interrupt epoch mismatch for {interrupt_id}: expected={req.epoch} provided={epoch}"
            )
        req.status = "resolved"
        return InterruptResolution(request=req, response=response)

    def clear_expired(self, run_id: str) -> int:
        """Clear expired."""
        now_ts = int(time.time())
        requests = self._requests.get(run_id, {})
        before = len(requests)
        alive = {
            req_id: req
            for req_id, req in requests.items()
            if req.expires_at > now_ts and req.status == "pending"
        }
        self._requests[run_id] = alive
        return before - len(alive)
