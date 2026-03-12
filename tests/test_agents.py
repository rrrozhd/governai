from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from governai import Agent, AgentRegistry, AgentResult, Workflow, step


class AgentIn(BaseModel):
    text: str


class AgentOut(BaseModel):
    summary: str


async def simple_handler(ctx, task):
    return AgentResult(status="final", output_payload={"summary": task.input_payload["text"]})


def make_agent(name: str) -> Agent:
    return Agent(
        name=name,
        description="simple",
        instruction="summarize",
        handler=simple_handler,
        input_model=AgentIn,
        output_model=AgentOut,
        allowed_tools=[],
        allowed_handoffs=[],
        max_turns=1,
        max_tool_calls=0,
    )


def test_agent_registry_duplicate_rejected() -> None:
    registry = AgentRegistry()
    agent = make_agent("a")
    registry.register(agent)
    with pytest.raises(ValueError):
        registry.register(agent)


def test_agent_step_execution_in_workflow() -> None:
    class AgentFlow(Workflow[AgentIn, AgentOut]):
        first = step("first", agent=make_agent("agent1")).then_end()

    async def run() -> None:
        flow = AgentFlow()
        state = await flow.run(AgentIn(text="hello"))
        assert state.status.value == "COMPLETED"
        assert state.artifacts["first"]["summary"] == "hello"

    asyncio.run(run())
