from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from typing import Any

from governai.models.run_state import RunState


class RunStore(ABC):
    """Persistence interface for workflow run state."""

    @abstractmethod
    async def put(self, state: RunState) -> None:
        """Persist a run state snapshot."""

    @abstractmethod
    async def get(self, run_id: str) -> RunState | None:
        """Fetch a run state snapshot."""

    @abstractmethod
    async def delete(self, run_id: str) -> None:
        """Delete persisted run state."""

    @abstractmethod
    async def write_checkpoint(self, state: RunState) -> str:
        """Persist one checkpoint snapshot and return checkpoint id."""

    @abstractmethod
    async def get_checkpoint(self, checkpoint_id: str) -> RunState | None:
        """Fetch checkpoint snapshot by checkpoint id."""

    @abstractmethod
    async def get_latest_checkpoint(self, thread_id: str) -> RunState | None:
        """Fetch latest checkpoint for a thread."""

    @abstractmethod
    async def list_checkpoints(self, thread_id: str) -> list[RunState]:
        """List checkpoints for a thread ordered by write sequence."""


class InMemoryRunStore(RunStore):
    """In-memory run store suitable for tests and local runs."""

    def __init__(self) -> None:
        """Initialize in-memory state and checkpoint indexes."""
        self._state: dict[str, RunState] = {}
        self._checkpoints: dict[str, RunState] = {}
        self._thread_checkpoints: dict[str, list[str]] = {}

    async def put(self, state: RunState) -> None:
        """Persist latest run snapshot and assign/write a checkpoint id."""
        checkpoint_id = await self.write_checkpoint(state)
        state.checkpoint_id = checkpoint_id
        self._state[state.run_id] = state.model_copy(deep=True)

    async def get(self, run_id: str) -> RunState | None:
        """Return a deep-copied run state snapshot by run id."""
        value = self._state.get(run_id)
        if value is None:
            return None
        return value.model_copy(deep=True)

    async def delete(self, run_id: str) -> None:
        """Delete persisted run state for the given run id."""
        self._state.pop(run_id, None)

    async def write_checkpoint(self, state: RunState) -> str:
        """Persist checkpoint snapshot and append it to the thread index."""
        checkpoint_id = state.checkpoint_id or str(uuid.uuid4())
        snapshot = state.model_copy(deep=True)
        snapshot.checkpoint_id = checkpoint_id
        self._checkpoints[checkpoint_id] = snapshot
        thread_list = self._thread_checkpoints.setdefault(state.thread_id, [])
        if checkpoint_id not in thread_list:
            thread_list.append(checkpoint_id)
        return checkpoint_id

    async def get_checkpoint(self, checkpoint_id: str) -> RunState | None:
        """Return checkpoint snapshot by id."""
        value = self._checkpoints.get(checkpoint_id)
        if value is None:
            return None
        return value.model_copy(deep=True)

    async def get_latest_checkpoint(self, thread_id: str) -> RunState | None:
        """Return the newest checkpoint snapshot for a thread id."""
        checkpoint_ids = self._thread_checkpoints.get(thread_id, [])
        if not checkpoint_ids:
            return None
        latest = self._checkpoints.get(checkpoint_ids[-1])
        if latest is None:
            return None
        return latest.model_copy(deep=True)

    async def list_checkpoints(self, thread_id: str) -> list[RunState]:
        """List all checkpoint snapshots for a thread in write order."""
        checkpoint_ids = self._thread_checkpoints.get(thread_id, [])
        out: list[RunState] = []
        for checkpoint_id in checkpoint_ids:
            snapshot = self._checkpoints.get(checkpoint_id)
            if snapshot is not None:
                out.append(snapshot.model_copy(deep=True))
        return out


class RedisRunStore(RunStore):
    """Redis-backed run store.

    The redis client is optional and can be injected for testing.
    """

    def __init__(
        self,
        *,
        redis_url: str,
        prefix: str = "governai:run",
        ttl_seconds: int | None = None,
        redis_client: Any | None = None,
    ) -> None:
        """Initialize Redis-backed run store configuration."""
        self.redis_url = redis_url
        self.prefix = prefix
        self.ttl_seconds = ttl_seconds
        self._redis = redis_client

    async def _client(self) -> Any:
        """Return cached redis client, creating it lazily when needed."""
        if self._redis is not None:
            return self._redis
        try:
            import redis.asyncio as redis  # type: ignore
        except Exception as exc:  # pragma: no cover - dependency optional
            raise RuntimeError(
                "RedisRunStore requires 'redis' package (redis.asyncio)"
            ) from exc
        self._redis = redis.from_url(self.redis_url, encoding="utf-8", decode_responses=True)
        return self._redis

    def _key(self, run_id: str) -> str:
        """Build redis key for a run snapshot."""
        return f"{self.prefix}:{run_id}"

    def _checkpoint_key(self, checkpoint_id: str) -> str:
        """Build redis key for a checkpoint snapshot."""
        return f"{self.prefix}:checkpoint:{checkpoint_id}"

    def _thread_index_key(self, thread_id: str) -> str:
        """Build redis list key that tracks checkpoint ids for one thread."""
        return f"{self.prefix}:thread:{thread_id}:checkpoints"

    async def put(self, state: RunState) -> None:
        """Persist latest run snapshot and assign/write a checkpoint id."""
        checkpoint_id = await self.write_checkpoint(state)
        state.checkpoint_id = checkpoint_id
        client = await self._client()
        payload = state.model_dump_json()
        key = self._key(state.run_id)
        if self.ttl_seconds is None:
            await client.set(key, payload)
        else:
            await client.set(key, payload, ex=int(self.ttl_seconds))

    async def get(self, run_id: str) -> RunState | None:
        """Fetch and decode one run snapshot by run id."""
        client = await self._client()
        payload = await client.get(self._key(run_id))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        if not isinstance(payload, str):
            payload = json.dumps(payload)
        return RunState.model_validate_json(payload)

    async def delete(self, run_id: str) -> None:
        """Delete persisted run snapshot by run id."""
        client = await self._client()
        await client.delete(self._key(run_id))

    async def write_checkpoint(self, state: RunState) -> str:
        """Write checkpoint payload and append checkpoint id to thread index."""
        client = await self._client()
        checkpoint_id = state.checkpoint_id or str(uuid.uuid4())
        # Keep checkpoint payload immutable from further in-memory mutations.
        payload_state = state.model_copy(deep=True)
        payload_state.checkpoint_id = checkpoint_id
        payload = payload_state.model_dump_json()
        key = self._checkpoint_key(checkpoint_id)
        if self.ttl_seconds is None:
            await client.set(key, payload)
        else:
            await client.set(key, payload, ex=int(self.ttl_seconds))
        await client.rpush(self._thread_index_key(state.thread_id), checkpoint_id)
        return checkpoint_id

    async def get_checkpoint(self, checkpoint_id: str) -> RunState | None:
        """Fetch and decode one checkpoint snapshot by checkpoint id."""
        client = await self._client()
        payload = await client.get(self._checkpoint_key(checkpoint_id))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        if not isinstance(payload, str):
            payload = json.dumps(payload)
        return RunState.model_validate_json(payload)

    async def get_latest_checkpoint(self, thread_id: str) -> RunState | None:
        """Fetch most recent checkpoint snapshot for a thread id."""
        client = await self._client()
        checkpoint_id = await client.lindex(self._thread_index_key(thread_id), -1)
        if checkpoint_id is None:
            return None
        if isinstance(checkpoint_id, bytes):
            checkpoint_id = checkpoint_id.decode("utf-8")
        return await self.get_checkpoint(str(checkpoint_id))

    async def list_checkpoints(self, thread_id: str) -> list[RunState]:
        """Fetch all checkpoints for a thread in insertion order."""
        client = await self._client()
        checkpoint_ids = await client.lrange(self._thread_index_key(thread_id), 0, -1)
        out: list[RunState] = []
        for checkpoint_id in checkpoint_ids:
            if isinstance(checkpoint_id, bytes):
                checkpoint_id = checkpoint_id.decode("utf-8")
            snapshot = await self.get_checkpoint(str(checkpoint_id))
            if snapshot is not None:
                out.append(snapshot)
        return out

    async def aclose(self) -> None:
        """Close underlying redis client if it exposes an async close hook."""
        if self._redis is None:
            return
        close = getattr(self._redis, "aclose", None)
        if callable(close):
            await close()
