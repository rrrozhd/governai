from __future__ import annotations

import asyncio

import pytest

from governai.models.policy import PolicyContext, PolicyDecision
from governai.policies.capability import CapabilityGrant, make_capability_policy
from governai.policies.engine import PolicyEngine
from governai.workflows.exceptions import PolicyDeniedError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ctx(
    capabilities: list[str],
    *,
    workflow_name: str = "wf",
    step_name: str = "step",
    tool_name: str = "tool",
) -> PolicyContext:
    return PolicyContext(
        workflow_name=workflow_name,
        step_name=step_name,
        tool_name=tool_name,
        capabilities=capabilities,
    )


def allow(grants: list[CapabilityGrant], ctx: PolicyContext) -> PolicyDecision:
    policy = make_capability_policy(grants)
    return policy(ctx)


# ---------------------------------------------------------------------------
# Scoping tests
# ---------------------------------------------------------------------------


def test_global_grant_allows() -> None:
    ctx = make_ctx(["net"], workflow_name="w", step_name="s")
    grant = CapabilityGrant(capability="net", scope="global")
    decision = allow([grant], ctx)
    assert decision.allow is True


def test_workflow_grant_allows() -> None:
    ctx = make_ctx(["db"], workflow_name="my_wf", step_name="s")
    grant = CapabilityGrant(capability="db", scope="workflow", target="my_wf")
    decision = allow([grant], ctx)
    assert decision.allow is True


def test_workflow_grant_wrong_workflow_denies() -> None:
    ctx = make_ctx(["db"], workflow_name="other_wf", step_name="s")
    grant = CapabilityGrant(capability="db", scope="workflow", target="my_wf")
    decision = allow([grant], ctx)
    assert decision.allow is False


def test_step_grant_allows() -> None:
    ctx = make_ctx(["fs"], workflow_name="wf", step_name="my_step")
    grant = CapabilityGrant(capability="fs", scope="step", target="my_step")
    decision = allow([grant], ctx)
    assert decision.allow is True


def test_step_grant_wrong_step_denies() -> None:
    ctx = make_ctx(["fs"], workflow_name="wf", step_name="other_step")
    grant = CapabilityGrant(capability="fs", scope="step", target="my_step")
    decision = allow([grant], ctx)
    assert decision.allow is False


# ---------------------------------------------------------------------------
# No-capability / empty tests
# ---------------------------------------------------------------------------


def test_no_capabilities_required_allows() -> None:
    ctx = make_ctx([], workflow_name="wf", step_name="s")
    decision = allow([], ctx)
    assert decision.allow is True


def test_empty_grants_list_no_capabilities_allows() -> None:
    ctx = make_ctx([])
    decision = allow([], ctx)
    assert decision.allow is True


# ---------------------------------------------------------------------------
# Deny diagnostic tests
# ---------------------------------------------------------------------------


def test_missing_capability_denies() -> None:
    ctx = make_ctx(["dangerous_op"])
    decision = allow([], ctx)
    assert decision.allow is False


def test_deny_diagnostic_message() -> None:
    ctx = make_ctx(["dangerous_op"])
    decision = allow([], ctx)
    assert decision.reason is not None
    assert "Missing capability: dangerous_op" in decision.reason
    assert "Required: [dangerous_op]" in decision.reason
    assert "Granted: []" in decision.reason


def test_partial_grant_denies_missing() -> None:
    ctx = make_ctx(["read", "write"])
    grants = [CapabilityGrant(capability="read", scope="global")]
    decision = allow(grants, ctx)
    assert decision.allow is False
    assert decision.reason is not None
    assert "write" in decision.reason
    assert "Missing capability: write" in decision.reason
    assert "read" in decision.reason


def test_multiple_grants_combine() -> None:
    ctx = make_ctx(["a", "b"], workflow_name="my_wf")
    grants = [
        CapabilityGrant(capability="a", scope="global"),
        CapabilityGrant(capability="b", scope="workflow", target="my_wf"),
    ]
    decision = allow(grants, ctx)
    assert decision.allow is True


# ---------------------------------------------------------------------------
# Model validation tests
# ---------------------------------------------------------------------------


def test_capability_grant_model_validation() -> None:
    grant = CapabilityGrant(capability="x")
    assert grant.scope == "global"
    assert grant.target is None


def test_grant_scoping() -> None:
    """Covers scope-aware matching across all three scopes."""
    global_grant = CapabilityGrant(capability="net", scope="global")
    wf_grant = CapabilityGrant(capability="db", scope="workflow", target="wf1")
    step_grant = CapabilityGrant(capability="fs", scope="step", target="step1")

    # Global applies everywhere
    assert allow([global_grant], make_ctx(["net"], workflow_name="any", step_name="any")).allow is True
    # Workflow-scoped: right workflow
    assert allow([wf_grant], make_ctx(["db"], workflow_name="wf1")).allow is True
    # Workflow-scoped: wrong workflow
    assert allow([wf_grant], make_ctx(["db"], workflow_name="wf2")).allow is False
    # Step-scoped: right step
    assert allow([step_grant], make_ctx(["fs"], step_name="step1")).allow is True
    # Step-scoped: wrong step
    assert allow([step_grant], make_ctx(["fs"], step_name="step2")).allow is False


# ---------------------------------------------------------------------------
# Engine integration test
# ---------------------------------------------------------------------------


def test_engine_integration() -> None:
    """PolicyEngine with registered capability policy denies tool with missing capability."""

    async def run() -> None:
        engine = PolicyEngine()
        capability_policy = make_capability_policy(grants=[])
        engine.register(capability_policy)

        ctx = make_ctx(["dangerous_op"])
        with pytest.raises(PolicyDeniedError):
            await engine.evaluate(workflow_name="wf", ctx=ctx)

    asyncio.run(run())


def test_engine_integration_allows_when_granted() -> None:
    """PolicyEngine allows when all required capabilities are granted."""

    async def run() -> None:
        engine = PolicyEngine()
        grants = [CapabilityGrant(capability="net", scope="global")]
        capability_policy = make_capability_policy(grants=grants)
        engine.register(capability_policy)

        ctx = make_ctx(["net"])
        results = await engine.evaluate(workflow_name="wf", ctx=ctx)
        assert len(results) == 1
        assert results[0][1].allow is True

    asyncio.run(run())
