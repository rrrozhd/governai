from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from governai import (
    ApprovalDecision,
    ApprovalDecisionType,
    ApprovalRejectedError,
    EventType,
    RunStatus,
    Workflow,
    step,
    tool,
)


class InModel(BaseModel):
    value: int


class MidModel(BaseModel):
    value: int


class OutModel(BaseModel):
    sent: bool


@tool(name="approval.prepare", input_model=InModel, output_model=MidModel)
async def prepare(ctx, data: InModel) -> MidModel:
    return MidModel(value=data.value)


@tool(
    name="approval.send",
    input_model=MidModel,
    output_model=OutModel,
    side_effect=True,
    requires_approval=True,
)
async def send(ctx, data: MidModel) -> OutModel:
    return OutModel(sent=True)


class ApprovalFlow(Workflow[InModel, OutModel]):
    prepare = step("prepare", tool=prepare).then("send")
    send = step("send", tool=send).then_end()


def test_approval_required_and_waiting() -> None:
    async def run() -> None:
        flow = ApprovalFlow()
        state = await flow.run(InModel(value=1))
        assert state.status == RunStatus.WAITING_APPROVAL
        assert state.pending_approval is not None

    asyncio.run(run())


def test_approval_approve_resumes_workflow() -> None:
    async def run() -> None:
        flow = ApprovalFlow()
        state = await flow.run(InModel(value=1))
        resumed = await flow.resume(
            state.run_id,
            ApprovalDecision(decision=ApprovalDecisionType.APPROVE, decided_by="tester"),
        )
        assert resumed.status == RunStatus.COMPLETED

    asyncio.run(run())


def test_approval_reject_fails_workflow() -> None:
    async def run() -> None:
        flow = ApprovalFlow()
        state = await flow.run(InModel(value=1))
        with pytest.raises(ApprovalRejectedError):
            await flow.resume(
                state.run_id,
                ApprovalDecision(decision=ApprovalDecisionType.REJECT, reason="nope"),
            )

    asyncio.run(run())


def test_approval_events_emitted() -> None:
    async def run() -> None:
        flow = ApprovalFlow()
        state = await flow.run(InModel(value=1))
        await flow.resume(state.run_id, ApprovalDecision(decision=ApprovalDecisionType.APPROVE))
        event_types = [event.event_type for event in flow.runtime.audit_emitter.events]
        assert EventType.APPROVAL_REQUESTED in event_types
        assert EventType.APPROVAL_GRANTED in event_types

    asyncio.run(run())
