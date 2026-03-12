from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from pydantic import BaseModel

from governai import (
    ApprovalDecision,
    ApprovalDecisionType,
    InMemoryAuditEmitter,
    PolicyDecision,
    Workflow,
    policy,
    step,
    tool,
    Tool,
)


class SupportIn(BaseModel):
    customer_id: str
    message: str
    to_email: str


class ValidateOut(BaseModel):
    customer_id: str
    message: str
    to_email: str


class FetchCustomerOut(BaseModel):
    customer_id: str
    email: str
    tier: str
    message: str


class DraftOut(BaseModel):
    subject: str
    body: str
    to_email: str


class SendOut(BaseModel):
    sent: bool
    provider_id: str


@tool(
    name="support.validate",
    input_model=SupportIn,
    output_model=ValidateOut,
    capabilities=["support.validate"],
)
async def validate_input(ctx, data: SupportIn) -> ValidateOut:
    if not data.message.strip():
        raise ValueError("message cannot be empty")
    return ValidateOut(**data.model_dump())


@tool(
    name="customer.fetch",
    input_model=ValidateOut,
    output_model=FetchCustomerOut,
    capabilities=["crm.read"],
)
async def fetch_customer(ctx, data: ValidateOut) -> FetchCustomerOut:
    return FetchCustomerOut(
        customer_id=data.customer_id,
        email=data.to_email,
        tier="gold",
        message=data.message,
    )


class DraftIn(BaseModel):
    customer_id: str
    tier: str
    message: str
    email: str


class DraftCliOut(BaseModel):
    subject: str
    body: str


SCRIPT_PATH = Path(__file__).resolve().parent / "scripts" / "draft_message.py"

draft_reply = Tool.from_cli(
    name="message.draft",
    command=[sys.executable, str(SCRIPT_PATH)],
    input_model=DraftIn,
    output_model=DraftCliOut,
    input_mode="json-stdin",
    output_mode="json-stdout",
    capabilities=["llm.invoke"],
)


class SendIn(BaseModel):
    subject: str
    body: str
    to_email: str


@tool(
    name="message.send",
    input_model=DraftOut,
    output_model=SendOut,
    capabilities=["email.send"],
    side_effect=True,
    requires_approval=True,
)
async def send_reply(ctx, data: DraftOut) -> SendOut:
    return SendOut(sent=True, provider_id=f"mock-{data.to_email}")


@tool(
    name="draft.shape",
    input_model=DraftCliOut,
    output_model=DraftOut,
)
async def draft_shape(ctx, data: DraftCliOut) -> DraftOut:
    fetch = ctx.get_artifact("fetch_customer")
    return DraftOut(subject=data.subject, body=data.body, to_email=fetch["email"])


@policy("deny_send_without_approval")
def deny_send_without_approval(ctx) -> PolicyDecision:
    if ctx.tool_name != "message.send":
        return PolicyDecision(allow=True)
    approved_steps = set(ctx.metadata.get("approved_steps", []))
    if ctx.step_name not in approved_steps:
        return PolicyDecision(allow=False, reason="external send requires explicit approval")
    return PolicyDecision(allow=True)


class SupportFlow(Workflow[SupportIn, SendOut]):
    validate = step("validate", tool=validate_input).then("fetch_customer")
    fetch_customer = step("fetch_customer", tool=fetch_customer).then("draft_reply")
    draft_reply = step("draft_reply", tool=draft_reply).then("draft_shape")
    draft_shape = step("draft_shape", tool=draft_shape).then("send_reply")
    send_reply = step("send_reply", tool=send_reply).then_end()


async def demo() -> None:
    audit = InMemoryAuditEmitter()
    flow = SupportFlow(audit_emitter=audit)
    flow.runtime.policy_engine.register(deny_send_without_approval)

    start = await flow.run(
        SupportIn(customer_id="cust-1", message="Need help with my billing", to_email="user@example.com")
    )
    print("First run status:", start.status)
    print("Pending approval:", start.pending_approval is not None)

    resumed = await flow.resume(
        start.run_id,
        ApprovalDecision(decision=ApprovalDecisionType.APPROVE, decided_by="demo"),
    )
    print("Final status:", resumed.status)
    print("Final artifact:", resumed.artifacts.get("send_reply"))
    print("Audit trail:")
    for event in audit.events:
        print(event.event_type.value, event.step_name, event.payload)


if __name__ == "__main__":
    asyncio.run(demo())
