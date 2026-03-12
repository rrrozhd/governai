from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from governai import (
    Agent,
    AgentLimitExceededError,
    AgentResult,
    AgentToolNotAllowedError,
    ToolRegistry,
    Workflow,
    step,
    tool,
)


class InModel(BaseModel):
    value: int


class MidModel(BaseModel):
    value: int


class OutModel(BaseModel):
    done: bool


@tool(name="echo.tool", input_model=MidModel, output_model=MidModel)
async def echo_tool(ctx, data: MidModel) -> MidModel:
    return data


async def disallowed_tool_handler(ctx, task):
    await ctx.use_tool("echo.tool", {"value": task.input_payload["value"]})
    return AgentResult(status="final", output_payload={"done": True})


async def too_many_calls_handler(ctx, task):
    await ctx.use_tool("echo.tool", {"value": task.input_payload["value"]})
    await ctx.use_tool("echo.tool", {"value": task.input_payload["value"]})
    return AgentResult(status="final", output_payload={"done": True})


def test_agent_disallowed_tool_call_rejected() -> None:
    agent = Agent(
        name="a",
        description="",
        instruction="",
        handler=disallowed_tool_handler,
        input_model=InModel,
        output_model=OutModel,
        allowed_tools=[],
        allowed_handoffs=[],
        max_tool_calls=1,
    )

    class Flow(Workflow[InModel, OutModel]):
        a = step("a", agent=agent).then_end()

    async def run() -> None:
        reg = ToolRegistry()
        reg.register(echo_tool)
        flow = Flow(tool_registry=reg)
        with pytest.raises(AgentToolNotAllowedError):
            await flow.run(InModel(value=1))

    asyncio.run(run())


def test_agent_max_tool_calls_enforced() -> None:
    agent = Agent(
        name="a2",
        description="",
        instruction="",
        handler=too_many_calls_handler,
        input_model=InModel,
        output_model=OutModel,
        allowed_tools=["echo.tool"],
        allowed_handoffs=[],
        max_tool_calls=1,
    )

    class Flow(Workflow[InModel, OutModel]):
        a = step("a", agent=agent).then_end()

    async def run() -> None:
        reg = ToolRegistry()
        reg.register(echo_tool)
        flow = Flow(tool_registry=reg)
        with pytest.raises(AgentLimitExceededError):
            await flow.run(InModel(value=1))

    asyncio.run(run())
