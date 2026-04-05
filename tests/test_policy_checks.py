from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from governai import EventType, PolicyDecision, PolicyDeniedError, Workflow, policy, step, tool
from governai.policies.base import _run_policy_isolated


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


# --- Fault isolation tests (TDD RED) ---


def test_policy_crash_produces_deny() -> None:
    """A policy that raises produces a deny decision with diagnostic reason."""

    async def run() -> None:
        from governai.models.policy import PolicyContext

        def bad_policy(ctx: PolicyContext) -> PolicyDecision:
            raise ValueError("boom")

        ctx = PolicyContext(
            workflow_name="test",
            step_name="only",
            tool_name="policy.echo",
        )
        decision = await _run_policy_isolated(bad_policy, ctx, "bad_policy", timeout=None)
        assert decision.allow is False
        assert "bad_policy" in decision.reason
        assert "ValueError" in decision.reason
        assert "boom" in decision.reason

    asyncio.run(run())


def test_policy_timeout_produces_deny() -> None:
    """A policy that exceeds its declared timeout produces a deny with timeout info."""

    async def run() -> None:
        from governai.models.policy import PolicyContext

        async def slow_policy(ctx: PolicyContext) -> PolicyDecision:
            await asyncio.sleep(10)
            return PolicyDecision(allow=True)

        slow_policy.__policy_timeout__ = 0.01

        ctx = PolicyContext(
            workflow_name="test",
            step_name="only",
            tool_name="policy.echo",
        )
        decision = await _run_policy_isolated(slow_policy, ctx, "slow_policy", timeout=0.01)
        assert decision.allow is False
        assert "slow_policy" in decision.reason
        assert "timed out" in decision.reason
        assert "0.01" in decision.reason

    asyncio.run(run())


def test_policy_no_timeout_runs_normally() -> None:
    """A policy with no timeout runs without any timeout enforcement."""

    async def run() -> None:
        from governai.models.policy import PolicyContext

        def normal_policy(ctx: PolicyContext) -> PolicyDecision:
            return PolicyDecision(allow=True, reason="all good")

        ctx = PolicyContext(
            workflow_name="test",
            step_name="only",
            tool_name="policy.echo",
        )
        decision = await _run_policy_isolated(normal_policy, ctx, "normal_policy", timeout=None)
        assert decision.allow is True
        assert decision.reason == "all good"

    asyncio.run(run())


def test_policy_crash_short_circuits() -> None:
    """After first policy crashes and denies, second policy is never called."""

    async def run() -> None:
        from governai.models.policy import PolicyContext

        tracker = {"second_called": False}

        def crashing_policy(ctx: PolicyContext) -> PolicyDecision:
            raise ValueError("crash")

        def second_policy(ctx: PolicyContext) -> PolicyDecision:
            tracker["second_called"] = True
            return PolicyDecision(allow=True)

        flow = PolicyFlow()
        flow.runtime.policy_engine.register(crashing_policy, name="crashing_policy")
        flow.runtime.policy_engine.register(second_policy, name="second_policy")

        with pytest.raises(PolicyDeniedError):
            await flow.run(InModel(value=1))

        assert tracker["second_called"] is False

    asyncio.run(run())
