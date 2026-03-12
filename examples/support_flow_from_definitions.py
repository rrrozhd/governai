from __future__ import annotations

import asyncio
from pathlib import Path

from governai import (
    AgentRegistry,
    ApprovalDecision,
    ApprovalDecisionType,
    ToolRegistry,
    governed_flow_from_config,
    governed_flow_from_dsl,
)

from support_flow import (
    SupportIn,
    deny_send_without_approval,
    draft_reply,
    draft_shape,
    fetch_customer,
    send_reply,
    validate_input,
)


def _tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for registered in [validate_input, fetch_customer, draft_reply, draft_shape, send_reply]:
        registry.register(registered)
    return registry


async def _run_with_approval(flow, payload: SupportIn):
    first = await flow.run(payload)
    if first.pending_approval is None:
        return first
    return await flow.resume(
        first.run_id,
        ApprovalDecision(decision=ApprovalDecisionType.APPROVE, decided_by="example"),
    )


async def demo() -> None:
    base = Path(__file__).resolve().parent
    config_path = base / "config" / "support_flow.yaml"
    dsl_path = base / "config" / "support_flow.dsl"

    policy_registry = {"deny_send_without_approval": deny_send_without_approval}

    config_flow = governed_flow_from_config(
        config_path,
        tool_registry=_tool_registry(),
        agent_registry=AgentRegistry(),
        policy_registry=policy_registry,
    )

    dsl_flow = governed_flow_from_dsl(
        dsl_path.read_text(encoding="utf-8"),
        tool_registry=_tool_registry(),
        agent_registry=AgentRegistry(),
        policy_registry=policy_registry,
    )

    payload = SupportIn(
        customer_id="cust-1",
        message="Need help with my billing",
        to_email="user@example.com",
    )

    config_state = await _run_with_approval(config_flow, payload)
    dsl_state = await _run_with_approval(dsl_flow, payload)

    print("Config status:", config_state.status)
    print("DSL status:", dsl_state.status)
    print("Artifacts match:", config_state.artifacts.get("send_reply") == dsl_state.artifacts.get("send_reply"))


if __name__ == "__main__":
    asyncio.run(demo())
