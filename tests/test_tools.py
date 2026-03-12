from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from governai import ToolValidationError, tool


class InModel(BaseModel):
    value: int


class OutModel(BaseModel):
    doubled: int


@tool(name="math.double", input_model=InModel, output_model=OutModel)
async def double_tool(ctx, data: InModel) -> OutModel:
    return OutModel(doubled=data.value * 2)


@tool(name="math.bad", input_model=InModel, output_model=OutModel)
async def bad_output_tool(ctx, data: InModel):
    return {"bad": "shape"}


def test_python_tool_validates_input_and_output_success() -> None:
    async def run() -> None:
        out = await double_tool.execute(None, {"value": 3})
        assert out.doubled == 6

    asyncio.run(run())


def test_python_tool_input_validation_error() -> None:
    async def run() -> None:
        with pytest.raises(ToolValidationError):
            await double_tool.execute(None, {"value": "x"})

    asyncio.run(run())


def test_python_tool_output_validation_error() -> None:
    async def run() -> None:
        with pytest.raises(ToolValidationError):
            await bad_output_tool.execute(None, {"value": 2})

    asyncio.run(run())
