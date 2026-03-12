from __future__ import annotations

import asyncio

from pydantic import BaseModel

from governai import EventType, InMemoryRunStore, Workflow, step, tool


class InModel(BaseModel):
    value: int


class OutModel(BaseModel):
    value: int


@tool(name="cp.add", input_model=InModel, output_model=OutModel)
async def add_one(ctx, data: InModel) -> OutModel:  # noqa: ARG001
    return OutModel(value=data.value + 1)


class CheckpointFlow(Workflow[InModel, OutModel]):
    first = step("first", tool=add_one).then_end()


def test_thread_and_checkpoint_lineage() -> None:
    async def run() -> None:
        store = InMemoryRunStore()
        flow = CheckpointFlow(run_store=store)
        state = await flow.run(InModel(value=3))
        assert state.thread_id == state.run_id
        assert state.checkpoint_id is not None

        latest = await store.get_latest_checkpoint(state.thread_id)
        assert latest is not None
        assert latest.checkpoint_id == state.checkpoint_id

        history = await store.list_checkpoints(state.thread_id)
        assert len(history) >= 2
        assert all(item.thread_id == state.thread_id for item in history)

        event_types = [event.event_type for event in flow.runtime.audit_emitter.events]
        assert EventType.CHECKPOINT_WRITTEN in event_types

    asyncio.run(run())


def test_resume_from_checkpoint() -> None:
    async def run() -> None:
        store = InMemoryRunStore()
        flow = CheckpointFlow(run_store=store)
        initial = await flow.run(InModel(value=1))
        checkpoints = await store.list_checkpoints(initial.thread_id)
        source = next((item for item in checkpoints if item.current_step == "first"), checkpoints[0])
        assert source.checkpoint_id is not None

        resumed = await flow.resume_from_checkpoint(source.checkpoint_id, {"value": 10})
        assert resumed.status.value == "COMPLETED"
        assert resumed.run_id != initial.run_id
        assert resumed.thread_id == initial.thread_id
        assert resumed.artifacts["first"]["value"] == 11

    asyncio.run(run())

