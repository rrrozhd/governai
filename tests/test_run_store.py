from __future__ import annotations

import asyncio

from governai.models.common import RunStatus
from governai.models.run_state import RunState
from governai.runtime.run_store import InMemoryRunStore, RedisRunStore


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:  # noqa: ARG002
        self.data[key] = value

    async def get(self, key: str):
        return self.data.get(key)

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)
        self.lists.pop(key, None)

    async def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)

    async def lindex(self, key: str, idx: int):
        values = self.lists.get(key, [])
        if not values:
            return None
        return values[idx]

    async def lrange(self, key: str, start: int, stop: int):  # noqa: ARG002
        values = self.lists.get(key, [])
        if stop == -1:
            stop = len(values) - 1
        return values[start : stop + 1]

    async def expire(self, key: str, seconds: int) -> None:  # noqa: ARG002
        return None

    async def aclose(self) -> None:
        return None


def _state(run_id: str) -> RunState:
    return RunState(
        run_id=run_id,
        thread_id=f"thread-{run_id}",
        workflow_name="Demo",
        status=RunStatus.RUNNING,
        current_step="s1",
    )


def test_inmemory_run_store_round_trip() -> None:
    async def run() -> None:
        store = InMemoryRunStore()
        src = _state("run1")
        await store.put(src)
        loaded = await store.get("run1")
        assert loaded is not None
        assert loaded.run_id == src.run_id
        assert loaded.current_step == "s1"

        loaded.current_step = "changed"
        loaded2 = await store.get("run1")
        assert loaded2 is not None
        assert loaded2.current_step == "s1"
        checkpoints = await store.list_checkpoints(src.thread_id)
        assert len(checkpoints) >= 1
        assert checkpoints[-1].run_id == "run1"

    asyncio.run(run())


def test_redis_run_store_with_injected_client() -> None:
    async def run() -> None:
        fake = FakeRedis()
        store = RedisRunStore(redis_url="redis://unused", redis_client=fake)
        await store.put(_state("run2"))
        loaded = await store.get("run2")
        assert loaded is not None
        assert loaded.run_id == "run2"
        latest = await store.get_latest_checkpoint("thread-run2")
        assert latest is not None
        assert latest.run_id == "run2"
        await store.delete("run2")
        assert await store.get("run2") is None
        await store.aclose()

    asyncio.run(run())
