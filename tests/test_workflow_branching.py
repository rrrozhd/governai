from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from governai import BranchResolutionError, Workflow, step, tool


class InModel(BaseModel):
    priority: str


class ClassifyOut(BaseModel):
    priority: str


class OutModel(BaseModel):
    result: str


@tool(name="branch.classify", input_model=InModel, output_model=ClassifyOut)
async def classify(ctx, data: InModel) -> ClassifyOut:
    return ClassifyOut(priority=data.priority)


@tool(name="branch.high", input_model=ClassifyOut, output_model=OutModel)
async def high(ctx, data: ClassifyOut) -> OutModel:
    return OutModel(result="high")


@tool(name="branch.normal", input_model=ClassifyOut, output_model=OutModel)
async def normal(ctx, data: ClassifyOut) -> OutModel:
    return OutModel(result="normal")


class BranchFlow(Workflow[InModel, OutModel]):
    classify = step("classify", tool=classify).branch(
        router="priority",
        mapping={"high": "high", "normal": "normal"},
    )
    high = step("high", tool=high).then_end()
    normal = step("normal", tool=normal).then_end()


def test_rule_based_branching_to_correct_step() -> None:
    async def run() -> None:
        flow = BranchFlow()
        state = await flow.run(InModel(priority="high"))
        assert state.completed_steps == ["classify", "high"]

    asyncio.run(run())


def test_rule_based_branching_unmapped_value_fails() -> None:
    async def run() -> None:
        flow = BranchFlow()
        with pytest.raises(BranchResolutionError):
            await flow.run(InModel(priority="unknown"))

    asyncio.run(run())
