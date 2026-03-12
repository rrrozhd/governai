from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from governai import Agent, AgentExecutionError, AgentResult, EventType, IllegalTransitionError, Workflow, step


class InModel(BaseModel):
    intent: str


class OutModel(BaseModel):
    done: bool


async def handoff_to_b(ctx, task):
    return AgentResult(status="handoff", next_agent="agent_b", output_payload={"intent": "x"})


async def handoff_to_c(ctx, task):
    return AgentResult(status="handoff", next_agent="agent_c", output_payload={"intent": "x"})


async def final_handler(ctx, task):
    return AgentResult(status="final", output_payload={"done": True})


agent_a = Agent(
    name="agent_a",
    description="a",
    instruction="",
    handler=handoff_to_b,
    input_model=InModel,
    output_model=InModel,
    allowed_tools=[],
    allowed_handoffs=["agent_b"],
)
agent_b = Agent(
    name="agent_b",
    description="b",
    instruction="",
    handler=final_handler,
    input_model=InModel,
    output_model=OutModel,
    allowed_tools=[],
    allowed_handoffs=[],
)


def test_agent_handoff_accepted() -> None:
    class HandoffFlow(Workflow[InModel, OutModel]):
        a = step("a", agent=agent_a).then("b")
        b = step("b", agent=agent_b).then_end()

    async def run() -> None:
        flow = HandoffFlow()
        state = await flow.run(InModel(intent="go"))
        assert state.status.value == "COMPLETED"
        types = [event.event_type for event in flow.runtime.audit_emitter.events]
        assert EventType.AGENT_HANDOFF_PROPOSED in types
        assert EventType.AGENT_HANDOFF_ACCEPTED in types

    asyncio.run(run())


def test_agent_handoff_must_match_transition() -> None:
    bad_agent_a = Agent(
        name="agent_a_bad",
        description="a",
        instruction="",
        handler=handoff_to_c,
        input_model=InModel,
        output_model=InModel,
        allowed_tools=[],
        allowed_handoffs=["agent_c"],
    )
    agent_c = Agent(
        name="agent_c",
        description="c",
        instruction="",
        handler=final_handler,
        input_model=InModel,
        output_model=OutModel,
        allowed_tools=[],
        allowed_handoffs=[],
    )

    class BadHandoffFlow(Workflow[InModel, OutModel]):
        a = step("a", agent=bad_agent_a).then("b")
        b = step("b", agent=agent_b).then_end()
        c = step("c", agent=agent_c).then_end()

    async def run() -> None:
        flow = BadHandoffFlow()
        with pytest.raises(IllegalTransitionError):
            await flow.run(InModel(intent="go"))

    asyncio.run(run())
