from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from governai import (
    Command,
    EventType,
    InterruptInstruction,
    ResumeInterrupt,
    RunStatus,
    Workflow,
    step,
    tool,
)


class AskInput(BaseModel):
    value: int


class ReplyInput(BaseModel):
    answer: str


class ReplyOut(BaseModel):
    result: str


@tool(name="cmd.ask", input_model=AskInput, output_model=Command)
async def ask_user(ctx, data: AskInput) -> Command:  # noqa: ARG001
    return Command(
        state_update={"history": {"asked": data.value}},
        interrupt=InterruptInstruction(message="Need user response"),
        goto="reply",
        output={"asked": data.value},
    )


@tool(name="cmd.ask.expired", input_model=AskInput, output_model=Command)
async def ask_user_expired(ctx, data: AskInput) -> Command:  # noqa: ARG001
    return Command(
        interrupt=InterruptInstruction(message="Need quick response", ttl_seconds=0),
        goto="reply",
        output={"asked": data.value},
    )


@tool(name="cmd.reply", input_model=ReplyInput, output_model=ReplyOut)
async def reply(ctx, data: ReplyInput) -> ReplyOut:  # noqa: ARG001
    return ReplyOut(result=f"ok:{data.answer}")


class InterruptFlow(Workflow[AskInput, ReplyOut]):
    ask = step("ask", tool=ask_user).then("reply")
    reply = step("reply", tool=reply).then_end()


class ExpiredInterruptFlow(Workflow[AskInput, ReplyOut]):
    ask = step("ask", tool=ask_user_expired).then("reply")
    reply = step("reply", tool=reply).then_end()


def test_command_interrupt_resume_path() -> None:
    async def run() -> None:
        flow = InterruptFlow(channel_reducers={"history": "merge"}, channel_defaults={"history": {}})
        state = await flow.run(AskInput(value=7))
        assert state.status == RunStatus.WAITING_INTERRUPT
        assert state.pending_interrupt_id is not None
        assert state.channels["history"] == {"asked": 7}

        resumed = await flow.resume(
            state.run_id,
            ResumeInterrupt(
                interrupt_id=state.pending_interrupt_id,
                response={"answer": "yes"},
                epoch=state.epoch,
            ),
        )
        assert resumed.status == RunStatus.COMPLETED
        assert resumed.artifacts["reply"]["result"] == "ok:yes"
        event_types = [event.event_type for event in flow.runtime.audit_emitter.events]
        assert EventType.INTERRUPT_REQUESTED in event_types
        assert EventType.INTERRUPT_RESOLVED in event_types

    asyncio.run(run())


def test_command_interrupt_epoch_mismatch_emits_event() -> None:
    async def run() -> None:
        flow = InterruptFlow()
        state = await flow.run(AskInput(value=1))
        assert state.pending_interrupt_id is not None
        with pytest.raises(ValueError):
            await flow.resume(
                state.run_id,
                ResumeInterrupt(
                    interrupt_id=state.pending_interrupt_id,
                    response={"answer": "no"},
                    epoch=state.epoch + 1,
                ),
            )
        event_types = [event.event_type for event in flow.runtime.audit_emitter.events]
        assert EventType.INTERRUPT_REJECTED_EPOCH in event_types

    asyncio.run(run())


def test_command_interrupt_ttl_expired() -> None:
    async def run() -> None:
        flow = ExpiredInterruptFlow()
        state = await flow.run(AskInput(value=3))
        assert state.pending_interrupt_id is not None
        with pytest.raises(ValueError):
            await flow.resume(
                state.run_id,
                ResumeInterrupt(
                    interrupt_id=state.pending_interrupt_id,
                    response={"answer": "late"},
                    epoch=state.epoch,
                ),
            )
        event_types = [event.event_type for event in flow.runtime.audit_emitter.events]
        assert EventType.INTERRUPT_EXPIRED in event_types

    asyncio.run(run())
