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


class MidModel(BaseModel):
    value: int


class OutModel(BaseModel):
    sent: bool


@tool(name="threaded.prepare", input_model=InModel, output_model=MidModel)
async def prepare(ctx, data: InModel) -> MidModel:  # noqa: ARG001
    return MidModel(value=data.value)


@tool(
    name="threaded.send",
    input_model=MidModel,
    output_model=OutModel,
    side_effect=True,
    requires_approval=True,
)
async def send(ctx, data: MidModel) -> OutModel:  # noqa: ARG001
    return OutModel(sent=True)


class ThreadedApprovalFlow(Workflow[InModel, OutModel]):
    prepare = step("prepare", tool=prepare).then("send")
    send = step("send", tool=send).then_end()


async def main() -> None:
    flow = ThreadedApprovalFlow(run_store=InMemoryRunStore())

    waiting = await flow.run(InModel(value=1), thread_id="thread-123")
    latest = await flow.get_latest_run_state("thread-123")
    print("waiting run:", waiting.run_id, waiting.status.value)
    print("latest run:", latest.run_id, latest.status.value)

    resumed = await flow.resume_latest(
        "thread-123",
        ApprovalDecision(decision=ApprovalDecisionType.APPROVE, decided_by="demo"),
    )
    print("resumed run:", resumed.run_id, resumed.status.value)
    print("thread history:", [state.run_id for state in await flow.list_thread_runs("thread-123")])


if __name__ == "__main__":
    asyncio.run(main())
