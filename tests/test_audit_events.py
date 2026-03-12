from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from governai import EventType, ToolExecutionError, Workflow, step, tool


class InModel(BaseModel):
    value: int


class OutModel(BaseModel):
    value: int


@tool(name="audit.ok", input_model=InModel, output_model=OutModel)
async def ok_tool(ctx, data: InModel) -> OutModel:
    return OutModel(value=data.value)


@tool(name="audit.fail", input_model=InModel, output_model=OutModel)
async def fail_tool(ctx, data: InModel) -> OutModel:
    raise RuntimeError("boom")


class HappyFlow(Workflow[InModel, OutModel]):
    only = step("only", tool=ok_tool).then_end()


class FailFlow(Workflow[InModel, OutModel]):
    only = step("only", tool=fail_tool).then_end()


def test_audit_events_happy_path_order() -> None:
    async def run() -> None:
        flow = HappyFlow()
        await flow.run(InModel(value=1))
        types = [
            event.event_type
            for event in flow.runtime.audit_emitter.events
            if event.event_type != EventType.CHECKPOINT_WRITTEN
        ]
        assert types == [
            EventType.RUN_STARTED,
            EventType.STEP_ENTERED,
            EventType.TOOL_EXECUTION_STARTED,
            EventType.TOOL_EXECUTION_COMPLETED,
            EventType.TRANSITION_CHOSEN,
            EventType.RUN_COMPLETED,
        ]

    asyncio.run(run())


def test_failure_path_emits_failure_events() -> None:
    async def run() -> None:
        flow = FailFlow()
        with pytest.raises(ToolExecutionError):
            await flow.run(InModel(value=1))
        types = [event.event_type for event in flow.runtime.audit_emitter.events]
        assert EventType.TOOL_EXECUTION_FAILED in types
        assert EventType.RUN_FAILED in types

    asyncio.run(run())
