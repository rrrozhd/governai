from __future__ import annotations

import asyncio

from pydantic import BaseModel

from governai import (
    Command,
    InterruptInstruction,
    RedisInterruptStore,
    RedisRunStore,
    ResumeInterrupt,
    RunStatus,
    Workflow,
    step,
    tool,
)


class AsyncFakeRedis:
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


class SyncFakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    def set(self, key: str, value: str) -> None:
        self.data[key] = value

    def get(self, key: str):
        return self.data.get(key)

    def delete(self, key: str) -> None:
        self.data.pop(key, None)
        self.lists.pop(key, None)

    def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)

    def lrange(self, key: str, start: int, stop: int):  # noqa: ARG002
        values = self.lists.get(key, [])
        if stop == -1:
            stop = len(values) - 1
        return values[start : stop + 1]

    def close(self) -> None:
        return None


class AskInput(BaseModel):
    value: int


class ReplyInput(BaseModel):
    answer: str


class ReplyOut(BaseModel):
    result: str


@tool(name="persist.ask", input_model=AskInput, output_model=Command)
async def ask_user(ctx, data: AskInput) -> Command:  # noqa: ARG001
    return Command(
        state_update={"history": {"asked": data.value}},
        interrupt=InterruptInstruction(message="Need user response"),
        goto="reply",
        output={"asked": data.value},
    )


@tool(name="persist.reply", input_model=ReplyInput, output_model=ReplyOut)
async def reply(ctx, data: ReplyInput) -> ReplyOut:  # noqa: ARG001
    return ReplyOut(result=f"ok:{data.answer}")


class InterruptFlow(Workflow[AskInput, ReplyOut]):
    ask = step("ask", tool=ask_user).then("reply")
    reply = step("reply", tool=reply).then_end()


def test_redis_interrupt_store_survives_runtime_recreation_and_supports_thread_helpers() -> None:
    async def run() -> None:
        async_redis = AsyncFakeRedis()
        sync_redis = SyncFakeRedis()
        run_store = RedisRunStore(redis_url="redis://unused", redis_client=async_redis)
        interrupt_store = RedisInterruptStore(redis_url="redis://unused", redis_client=sync_redis)

        flow_a = InterruptFlow(
            run_store=run_store,
            interrupt_store=interrupt_store,
            channel_reducers={"history": "merge"},
            channel_defaults={"history": {}},
        )
        waiting = await flow_a.run(AskInput(value=7), thread_id="thread-interrupt")
        assert waiting.status == RunStatus.WAITING_INTERRUPT
        assert waiting.pending_interrupt_id is not None
        assert await run_store.get_active_run_id("thread-interrupt") == waiting.run_id

        flow_b = InterruptFlow(
            run_store=run_store,
            interrupt_store=RedisInterruptStore(redis_url="redis://unused", redis_client=sync_redis),
            channel_reducers={"history": "merge"},
            channel_defaults={"history": {}},
        )
        latest = await flow_b.get_latest_run_state("thread-interrupt")
        assert latest.run_id == waiting.run_id

        pending = await flow_b.list_pending_interrupts(waiting.run_id)
        assert len(pending) == 1
        assert pending[0].interrupt_id == waiting.pending_interrupt_id
        latest_pending = await flow_b.get_latest_pending_interrupt(waiting.run_id)
        assert latest_pending is not None
        assert latest_pending.interrupt_id == waiting.pending_interrupt_id
        thread_pending = await flow_b.list_thread_pending_interrupts("thread-interrupt")
        assert [item.interrupt_id for item in thread_pending] == [waiting.pending_interrupt_id]

        resumed = await flow_b.resume_latest(
            "thread-interrupt",
            ResumeInterrupt(
                interrupt_id=waiting.pending_interrupt_id,
                response={"answer": "yes"},
                epoch=waiting.epoch,
            ),
        )
        assert resumed.status == RunStatus.COMPLETED
        assert resumed.artifacts["reply"]["result"] == "ok:yes"
        assert await run_store.get_active_run_id("thread-interrupt") is None

    asyncio.run(run())
