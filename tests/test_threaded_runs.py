from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from governai import (
    ApprovalDecision,
    ApprovalDecisionType,
    EventType,
    GovernedFlowSpec,
    GovernedStepSpec,
    InMemoryRunStore,
    RunStatus,
    ToolExecutionError,
    Workflow,
    end,
    governed_flow,
    step,
    then,
    tool,
)


class InModel(BaseModel):
    value: int


class MidModel(BaseModel):
    value: int


class OutModel(BaseModel):
    value: int


class ApprovalOut(BaseModel):
    sent: bool


@tool(name="thread.add", input_model=InModel, output_model=OutModel)
async def add_one(ctx, data: InModel) -> OutModel:  # noqa: ARG001
    return OutModel(value=data.value + 1)


@tool(name="thread.prepare", input_model=InModel, output_model=MidModel)
async def prepare(ctx, data: InModel) -> MidModel:  # noqa: ARG001
    return MidModel(value=data.value)


@tool(
    name="thread.send",
    input_model=MidModel,
    output_model=ApprovalOut,
    requires_approval=True,
    side_effect=True,
)
async def send(ctx, data: MidModel) -> ApprovalOut:  # noqa: ARG001
    return ApprovalOut(sent=True)


@tool(name="thread.fail", input_model=InModel, output_model=OutModel)
async def fail_tool(ctx, data: InModel) -> OutModel:  # noqa: ARG001
    raise RuntimeError(f"boom:{data.value}")


class ThreadFlow(Workflow[InModel, OutModel]):
    only = step("only", tool=add_one).then_end()


class ApprovalFlow(Workflow[InModel, ApprovalOut]):
    prepare = step("prepare", tool=prepare).then("send")
    send = step("send", tool=send).then_end()


class FailingFlow(Workflow[InModel, OutModel]):
    only = step("only", tool=fail_tool).then_end()


def test_run_without_thread_id_preserves_current_behavior_and_audit_thread_id() -> None:
    async def run() -> None:
        flow = ThreadFlow()
        state = await flow.run(InModel(value=1))
        assert state.thread_id == state.run_id
        event_types = [event.event_type for event in flow.runtime.audit_emitter.events]
        assert EventType.RUN_STARTED in event_types
        assert all(event.thread_id == state.thread_id for event in flow.runtime.audit_emitter.events)

    asyncio.run(run())


def test_thread_helpers_track_active_and_latest_runs() -> None:
    async def run() -> None:
        store = InMemoryRunStore()
        flow = ApprovalFlow(run_store=store)

        waiting = await flow.run(InModel(value=3), thread_id="thread-123")
        assert waiting.thread_id == "thread-123"
        assert waiting.status == RunStatus.WAITING_APPROVAL
        assert await store.get_active_run_id("thread-123") == waiting.run_id

        latest_waiting = await flow.get_latest_run_state("thread-123")
        assert latest_waiting.run_id == waiting.run_id
        assert [state.run_id for state in await flow.list_thread_runs("thread-123")] == [waiting.run_id]

        resumed = await flow.resume_latest(
            "thread-123",
            ApprovalDecision(decision=ApprovalDecisionType.APPROVE, decided_by="tester"),
        )
        assert resumed.status == RunStatus.COMPLETED
        assert await store.get_active_run_id("thread-123") is None

        second = await ThreadFlow(run_store=store).run(InModel(value=9), thread_id="thread-123")
        latest = await ThreadFlow(run_store=store).get_latest_run_state("thread-123")
        assert latest.run_id == second.run_id
        history = await ThreadFlow(run_store=store).list_thread_runs("thread-123")
        assert [item.run_id for item in history] == [waiting.run_id, second.run_id]

    asyncio.run(run())


def test_failed_runs_clear_active_mapping_but_remain_queryable() -> None:
    async def run() -> None:
        store = InMemoryRunStore()
        flow = FailingFlow(run_store=store)
        with pytest.raises(ToolExecutionError, match="boom:5"):
            await flow.run(InModel(value=5), thread_id="thread-fail")
        assert await store.get_active_run_id("thread-fail") is None
        latest = await flow.get_latest_run_state("thread-fail")
        assert latest.status == RunStatus.FAILED
        assert latest.error is not None

    asyncio.run(run())


def test_resume_from_checkpoint_preserves_thread_and_replaces_active_run() -> None:
    async def run() -> None:
        store = InMemoryRunStore()
        flow = ApprovalFlow(run_store=store)
        initial = await flow.run(InModel(value=7), thread_id="thread-checkpoint")
        checkpoints = await store.list_checkpoints("thread-checkpoint")
        source = next(
            item
            for item in checkpoints
            if item.current_step == "send" and item.pending_approval is None and item.status == RunStatus.RUNNING
        )
        assert source.checkpoint_id is not None
        resumed = await flow.resume_from_checkpoint(source.checkpoint_id, {"value": 7})
        assert resumed.thread_id == initial.thread_id
        assert resumed.status == RunStatus.WAITING_APPROVAL
        assert resumed.run_id != initial.run_id
        assert await store.get_active_run_id("thread-checkpoint") == resumed.run_id

    asyncio.run(run())


def test_governed_flow_thread_helpers_delegate_to_workflow() -> None:
    async def run() -> None:
        spec = GovernedFlowSpec(
            name="thread_spec",
            steps=[GovernedStepSpec(name="only", tool=add_one, transition=end())],
        )
        flow = governed_flow(spec, run_store=InMemoryRunStore())
        state = await flow.run(InModel(value=4), thread_id="thread-governed")
        latest = await flow.get_latest_run_state("thread-governed")
        history = await flow.list_thread_runs("thread-governed")
        assert state.thread_id == "thread-governed"
        assert latest.run_id == state.run_id
        assert [item.run_id for item in history] == [state.run_id]

    asyncio.run(run())
