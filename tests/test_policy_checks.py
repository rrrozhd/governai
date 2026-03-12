from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from governai import EventType, PolicyDecision, PolicyDeniedError, Workflow, policy, step, tool


class InModel(BaseModel):
    value: int


class OutModel(BaseModel):
    value: int


calls = {"count": 0}


@tool(name="policy.echo", input_model=InModel, output_model=OutModel)
async def echo(ctx, data: InModel) -> OutModel:
    calls["count"] += 1
    return OutModel(value=data.value)


@policy("allow_all")
def allow_all(ctx):
    return PolicyDecision(allow=True)


@policy("deny_all")
def deny_all(ctx):
    return PolicyDecision(allow=False, reason="blocked")


class PolicyFlow(Workflow[InModel, OutModel]):
    only = step("only", tool=echo).then_end()


def test_policy_allow() -> None:
    async def run() -> None:
        calls["count"] = 0
        flow = PolicyFlow()
        flow.runtime.policy_engine.register(allow_all)
        state = await flow.run(InModel(value=1))
        assert state.status.value == "COMPLETED"
        assert calls["count"] == 1

    asyncio.run(run())


def test_policy_deny_blocks_before_tool_runs() -> None:
    async def run() -> None:
        calls["count"] = 0
        flow = PolicyFlow()
        flow.runtime.policy_engine.register(deny_all)
        with pytest.raises(PolicyDeniedError):
            await flow.run(InModel(value=1))
        assert calls["count"] == 0

    asyncio.run(run())


def test_policy_events_emitted() -> None:
    async def run() -> None:
        flow = PolicyFlow()
        flow.runtime.policy_engine.register(deny_all)
        with pytest.raises(PolicyDeniedError):
            await flow.run(InModel(value=1))
        event_types = [event.event_type for event in flow.runtime.audit_emitter.events]
        assert EventType.POLICY_CHECKED in event_types
        assert EventType.POLICY_DENIED in event_types

    asyncio.run(run())
