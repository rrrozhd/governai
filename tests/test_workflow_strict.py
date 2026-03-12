from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from governai import Workflow, WorkflowDefinitionError, step, tool


class InModel(BaseModel):
    value: int


class MidModel(BaseModel):
    value: int


class OutModel(BaseModel):
    final: int


@tool(name="strict.first", input_model=InModel, output_model=MidModel)
async def first(ctx, data: InModel) -> MidModel:
    return MidModel(value=data.value + 1)


@tool(name="strict.second", input_model=MidModel, output_model=OutModel)
async def second(ctx, data: MidModel) -> OutModel:
    assert ctx.get_artifact("first")["value"] == data.value
    return OutModel(final=data.value * 2)


class StrictFlow(Workflow[InModel, OutModel]):
    first = step("first", tool=first).then("second")
    second = step("second", tool=second).then_end()


def test_workflow_strict_execution_order_and_artifacts() -> None:
    async def run() -> None:
        flow = StrictFlow()
        state = await flow.run(InModel(value=2))
        assert state.status.value == "COMPLETED"
        assert state.completed_steps == ["first", "second"]
        assert state.artifacts["second"]["final"] == 6

    asyncio.run(run())


def test_workflow_missing_next_step_in_definition() -> None:
    with pytest.raises(WorkflowDefinitionError):

        class BadFlow(Workflow[InModel, OutModel]):
            first = step("first", tool=first).then("missing")
