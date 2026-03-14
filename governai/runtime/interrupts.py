from __future__ import annotations

import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
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


class InterruptStore(ABC):
    """Persistence backend for interrupt requests and per-run epochs."""

    blocking_io: bool = False

    @abstractmethod
    def get_epoch(self, run_id: str) -> int:
        """Return the persisted epoch for a run."""

    @abstractmethod
    def set_epoch(self, run_id: str, epoch: int) -> None:
        """Persist the epoch for a run."""

    @abstractmethod
    def save_request(self, request: InterruptRequest) -> None:
        """Persist one interrupt request."""

    @abstractmethod
    def get_request(self, run_id: str, interrupt_id: str) -> InterruptRequest | None:
        """Fetch one interrupt request by id."""

    @abstractmethod
    def list_requests(self, run_id: str) -> list[InterruptRequest]:
        """List all stored interrupt requests for a run."""

    @abstractmethod
    def delete_request(self, run_id: str, interrupt_id: str) -> None:
        """Delete one stored interrupt request."""


class InMemoryInterruptStore(InterruptStore):
    """In-memory interrupt persistence."""

    def __init__(self) -> None:
        """Initialize in-memory interrupt indexes."""
        self._requests: dict[str, dict[str, InterruptRequest]] = {}
        self._epochs: dict[str, int] = {}

    def get_epoch(self, run_id: str) -> int:
        """Return the current epoch for a run."""
        return self._epochs.get(run_id, 0)

    def set_epoch(self, run_id: str, epoch: int) -> None:
        """Persist the current epoch for a run."""
        self._epochs[run_id] = epoch

    def save_request(self, request: InterruptRequest) -> None:
        """Persist one request object."""
        self._requests.setdefault(request.run_id, {})[request.interrupt_id] = request

    def get_request(self, run_id: str, interrupt_id: str) -> InterruptRequest | None:
        """Fetch one request object by run and interrupt id."""
        return self._requests.get(run_id, {}).get(interrupt_id)

    def list_requests(self, run_id: str) -> list[InterruptRequest]:
        """List all request objects for a run."""
        return list(self._requests.get(run_id, {}).values())

    def delete_request(self, run_id: str, interrupt_id: str) -> None:
        """Delete one request object."""
        requests = self._requests.get(run_id)
        if requests is None:
            return
        requests.pop(interrupt_id, None)
        if not requests:
            self._requests.pop(run_id, None)


class RedisInterruptStore(InterruptStore):
    """Redis-backed durable interrupt persistence."""

    blocking_io = True

    def __init__(
        self,
        *,
        redis_url: str,
        prefix: str = "governai:interrupt",
        redis_client: Any | None = None,
    ) -> None:
        """Initialize Redis interrupt store configuration."""
        self.redis_url = redis_url
        self.prefix = prefix
        self._redis = redis_client

    def _client(self) -> Any:
        """Return cached redis client, creating it lazily when needed."""
        if self._redis is not None:
            return self._redis
        try:
            import redis  # type: ignore
        except Exception as exc:  # pragma: no cover - dependency optional
            raise RuntimeError("RedisInterruptStore requires 'redis' package") from exc
        self._redis = redis.Redis.from_url(self.redis_url, encoding="utf-8", decode_responses=True)
        return self._redis

    @staticmethod
    def _decode_text(value: Any) -> str | None:
        """Normalize redis return values into text."""
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        if isinstance(value, str):
            return value
        return str(value)

    def _epoch_key(self, run_id: str) -> str:
        """Build redis key for run epoch."""
        return f"{self.prefix}:run:{run_id}:epoch"

    def _request_key(self, run_id: str, interrupt_id: str) -> str:
        """Build redis key for one interrupt request."""
        return f"{self.prefix}:run:{run_id}:request:{interrupt_id}"

    def _request_index_key(self, run_id: str) -> str:
        """Build redis list key for interrupt ids in insertion order."""
        return f"{self.prefix}:run:{run_id}:requests"

    def _rewrite_list(self, key: str, values: list[str]) -> None:
        """Rewrite one redis list key from scratch."""
        client = self._client()
        client.delete(key)
        for value in values:
            client.rpush(key, value)

    def get_epoch(self, run_id: str) -> int:
        """Return the persisted epoch for a run."""
        client = self._client()
        payload = self._decode_text(client.get(self._epoch_key(run_id)))
        if payload is None:
            return 0
        return int(payload)

    def set_epoch(self, run_id: str, epoch: int) -> None:
        """Persist the current epoch for a run."""
        self._client().set(self._epoch_key(run_id), str(int(epoch)))

    def save_request(self, request: InterruptRequest) -> None:
        """Persist one interrupt request."""
        client = self._client()
        client.set(self._request_key(request.run_id, request.interrupt_id), json.dumps(asdict(request)))
        index_key = self._request_index_key(request.run_id)
        existing = [value for value in client.lrange(index_key, 0, -1)]
        normalized = [current for current in (self._decode_text(value) for value in existing) if current is not None]
        if request.interrupt_id not in normalized:
            client.rpush(index_key, request.interrupt_id)

    def get_request(self, run_id: str, interrupt_id: str) -> InterruptRequest | None:
        """Fetch one interrupt request by id."""
        payload = self._decode_text(self._client().get(self._request_key(run_id, interrupt_id)))
        if payload is None:
            return None
        return InterruptRequest(**json.loads(payload))

    def list_requests(self, run_id: str) -> list[InterruptRequest]:
        """List all stored interrupt requests for a run."""
        client = self._client()
        raw_ids = client.lrange(self._request_index_key(run_id), 0, -1)
        normalized = [current for current in (self._decode_text(value) for value in raw_ids) if current is not None]
        valid_ids: list[str] = []
        out: list[InterruptRequest] = []
        for interrupt_id in normalized:
            request = self.get_request(run_id, interrupt_id)
            if request is None:
                continue
            valid_ids.append(interrupt_id)
            out.append(request)
        if valid_ids != normalized:
            self._rewrite_list(self._request_index_key(run_id), valid_ids)
        return out

    def delete_request(self, run_id: str, interrupt_id: str) -> None:
        """Delete one stored interrupt request."""
        client = self._client()
        client.delete(self._request_key(run_id, interrupt_id))
        raw_ids = client.lrange(self._request_index_key(run_id), 0, -1)
        normalized = [current for current in (self._decode_text(value) for value in raw_ids) if current is not None]
        filtered = [current for current in normalized if current != interrupt_id]
        self._rewrite_list(self._request_index_key(run_id), filtered)

    def close(self) -> None:
        """Close underlying redis client if it exposes a sync close hook."""
        if self._redis is None:
            return
        close = getattr(self._redis, "close", None)
        if callable(close):
            close()


class InterruptManager:
    """Tracks non-approval interrupts with TTL and epoch guards."""

    def __init__(self, *, default_ttl_seconds: int = 1800, store: InterruptStore | None = None) -> None:
        """Initialize InterruptManager."""
        self.default_ttl_seconds = default_ttl_seconds
        self.store = store or InMemoryInterruptStore()

    def uses_blocking_io(self) -> bool:
        """Return whether the backing store performs blocking I/O."""
        return bool(getattr(self.store, "blocking_io", False))

    def current_epoch(self, run_id: str) -> int:
        """Current epoch."""
        return self.store.get_epoch(run_id)

    def bump_epoch(self, run_id: str) -> int:
        """Bump epoch."""
        next_epoch = self.current_epoch(run_id) + 1
        self.store.set_epoch(run_id, next_epoch)
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
        self.store.save_request(request)
        return request

    def get_pending(self, run_id: str, interrupt_id: str) -> InterruptRequest | None:
        """Return one pending interrupt request when it still exists and is live."""
        req = self.store.get_request(run_id, interrupt_id)
        if req is None or req.status != "pending":
            return None
        if req.expires_at <= int(time.time()):
            req.status = "expired"
            self.store.save_request(req)
            return None
        return req

    def get_latest_pending(self, run_id: str, *, epoch: int | None = None) -> InterruptRequest | None:
        """Return the newest pending interrupt for a run."""
        pending = self.list_pending(run_id, epoch=epoch)
        if not pending:
            return None
        return pending[-1]

    def list_pending(self, run_id: str, *, epoch: int | None = None) -> list[InterruptRequest]:
        """List pending."""
        now_ts = int(time.time())
        requests = self.store.list_requests(run_id)
        out: list[InterruptRequest] = []
        for req in requests:
            if req.status != "pending":
                continue
            if req.expires_at <= now_ts:
                req.status = "expired"
                self.store.save_request(req)
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
        req = self.store.get_request(run_id, interrupt_id)
        if req is None:
            raise KeyError(f"Unknown interrupt_id: {interrupt_id}")
        if req.status != "pending":
            raise ValueError(f"Interrupt {interrupt_id} is not pending")
        if req.expires_at <= int(time.time()):
            req.status = "expired"
            self.store.save_request(req)
            raise ValueError(f"Interrupt {interrupt_id} has expired")
        if epoch is not None and req.epoch != epoch:
            raise ValueError(
                f"Interrupt epoch mismatch for {interrupt_id}: expected={req.epoch} provided={epoch}"
            )
        req.status = "resolved"
        self.store.save_request(req)
        return InterruptResolution(request=req, response=response)

    def clear_expired(self, run_id: str) -> int:
        """Clear expired and resolved requests for one run."""
        now_ts = int(time.time())
        removed = 0
        for req in self.store.list_requests(run_id):
            if req.status != "pending" or req.expires_at <= now_ts:
                self.store.delete_request(run_id, req.interrupt_id)
                removed += 1
        return removed
