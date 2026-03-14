from __future__ import annotations

import asyncio

from governai.audit.redis import RedisAuditEmitter
from governai.models.audit import AuditEvent
from governai.models.common import EventType


class FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}

    async def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)

    async def lrange(self, key: str, start: int, stop: int):  # noqa: ARG002
        values = self.lists.get(key, [])
        if stop == -1:
            stop = len(values) - 1
        return values[start : stop + 1]

    async def expire(self, key: str, seconds: int) -> None:  # noqa: ARG002
        return None

    async def aclose(self) -> None:
        return None


def test_redis_audit_emitter_round_trip() -> None:
    async def run() -> None:
        fake = FakeRedis()
        emitter = RedisAuditEmitter(redis_url="redis://unused", redis_client=fake)
        event = AuditEvent(
            event_id="e1",
            run_id="r1",
            thread_id="thread-1",
            workflow_name="wf",
            event_type=EventType.RUN_STARTED,
            payload={"a": 1},
        )
        await emitter.emit(event)
        events = await emitter.events_for_run("r1")
        assert len(events) == 1
        assert events[0].thread_id == "thread-1"
        assert events[0].payload == {"a": 1}
        await emitter.aclose()

    asyncio.run(run())
