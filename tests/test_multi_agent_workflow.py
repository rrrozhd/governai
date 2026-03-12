from __future__ import annotations

import asyncio

from pydantic import BaseModel

from governai import Agent, AgentResult, Workflow, step


class InModel(BaseModel):
    intent: str


class TriageOut(BaseModel):
    intent: str


class FinalOut(BaseModel):
    result: str


async def triage_handler(ctx, task):
    intent = task.input_payload["intent"]
    return AgentResult(status="final", output_payload={"intent": intent})


async def refund_handler(ctx, task):
    return AgentResult(status="final", output_payload={"result": "refund"})


async def tech_handler(ctx, task):
    return AgentResult(status="final", output_payload={"result": "tech"})


triage_agent = Agent(
    name="triage_agent",
    description="",
    instruction="",
    handler=triage_handler,
    input_model=InModel,
    output_model=TriageOut,
    allowed_tools=[],
    allowed_handoffs=["refund_agent", "tech_agent"],
)
refund_agent = Agent(
    name="refund_agent",
    description="",
    instruction="",
    handler=refund_handler,
    input_model=TriageOut,
    output_model=FinalOut,
    allowed_tools=[],
    allowed_handoffs=[],
)
tech_agent = Agent(
    name="tech_agent",
    description="",
    instruction="",
    handler=tech_handler,
    input_model=TriageOut,
    output_model=FinalOut,
    allowed_tools=[],
    allowed_handoffs=[],
)


class MultiAgentFlow(Workflow[InModel, FinalOut]):
    triage = step("triage", agent=triage_agent).branch(
        router="intent",
        mapping={"refund": "refund", "technical": "tech"},
    )
    refund = step("refund", agent=refund_agent).then_end()
    tech = step("tech", agent=tech_agent).then_end()


def test_multi_agent_branching_flow() -> None:
    async def run() -> None:
        flow = MultiAgentFlow()
        refund_state = await flow.run(InModel(intent="refund"))
        assert refund_state.artifacts["refund"]["result"] == "refund"

        tech_state = await flow.run(InModel(intent="technical"))
        assert tech_state.artifacts["tech"]["result"] == "tech"

    asyncio.run(run())
