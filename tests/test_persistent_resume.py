from __future__ import annotations

import asyncio

from pydantic import BaseModel

from governai import (
    ApprovalDecision,
    ApprovalDecisionType,
    InMemoryRunStore,
    Workflow,
    step,
    tool,
)


class InModel(BaseModel):
    value: int


class OutModel(BaseModel):
    value: int


@tool(
    name="persist.send",
    input_model=InModel,
    output_model=OutModel,
    requires_approval=True,
    side_effect=True,
)
async def gated_send(ctx, data: InModel) -> OutModel:  # noqa: ARG001
    return OutModel(value=data.value)


class PersistFlow(Workflow[InModel, OutModel]):
    only = step("only", tool=gated_send).then_end()


def test_resume_can_load_state_from_run_store() -> None:
    async def run() -> None:
        store = InMemoryRunStore()

        flow_a = PersistFlow(run_store=store)
        state = await flow_a.run(InModel(value=7))
        assert state.status.value == "WAITING_APPROVAL"

        flow_b = PersistFlow(run_store=store)
        resumed = await flow_b.resume(
            state.run_id,
            ApprovalDecision(decision=ApprovalDecisionType.APPROVE, decided_by="tester"),
        )
        assert resumed.status.value == "COMPLETED"
        assert resumed.artifacts["only"]["value"] == 7

    asyncio.run(run())
