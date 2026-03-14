from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel

from governai import (
    Agent,
    AgentRegistry,
    AgentResult,
    HTTPSandboxExecutionAdapter,
    ToolRegistry,
    Workflow,
    create_sandbox_app,
    step,
    tool,
)


class PromptIn(BaseModel):
    text: str


class DraftOut(BaseModel):
    text: str


class ReviewOut(BaseModel):
    approved: bool
    text: str


# Control-plane executors: these objects define governance policy and remote routing.
# They must not execute on the host in strict_remote mode.
@tool(
    name="example.remote.draft",
    input_model=PromptIn,
    output_model=DraftOut,
    execution_placement="remote_only",
    remote_name="sandbox.remote.draft",
)
async def control_plane_draft(ctx, data: PromptIn) -> DraftOut:  # noqa: ARG001
    raise RuntimeError("strict_remote should never execute draft on the control plane")


async def control_plane_reviewer(ctx, task):  # noqa: ARG001
    raise RuntimeError("strict_remote should never execute agents on the control plane")


review_agent = Agent(
    name="example.remote.review",
    description="Review a generated draft and return the final decision.",
    instruction="Draft the response, then approve it if it is concise and safe.",
    handler=control_plane_reviewer,
    input_model=PromptIn,
    output_model=ReviewOut,
    allowed_tools=["example.remote.draft"],
    allowed_handoffs=[],
    max_tool_calls=1,
    execution_placement="remote_only",
    remote_name="sandbox.remote.review",
)


class RemoteReviewFlow(Workflow[PromptIn, ReviewOut]):
    review = step("review", agent=review_agent).then_end()


# Sandbox executors: these live on the worker machine and resolve by remote_name.
@tool(
    name="example.remote.draft.worker",
    input_model=PromptIn,
    output_model=DraftOut,
    remote_name="sandbox.remote.draft",
)
async def sandbox_draft(ctx, data: PromptIn) -> DraftOut:  # noqa: ARG001
    return DraftOut(text=f"Draft: {data.text.strip()}")


async def sandbox_reviewer(ctx, task):
    draft = await ctx.use_tool("example.remote.draft", {"text": task.input_payload["text"]})
    return AgentResult(
        status="final",
        output_payload={"approved": True, "text": draft["text"]},
    )


sandbox_review_agent = Agent(
    name="example.remote.review.worker",
    description="Worker-side review agent.",
    instruction="Draft the response, then approve it if it is concise and safe.",
    handler=sandbox_reviewer,
    input_model=PromptIn,
    output_model=ReviewOut,
    allowed_tools=["example.remote.draft"],
    allowed_handoffs=[],
    max_tool_calls=1,
    remote_name="sandbox.remote.review",
)


def build_worker_app() -> Any:
    tool_registry = ToolRegistry()
    tool_registry.register(sandbox_draft)

    agent_registry = AgentRegistry()
    agent_registry.register(sandbox_review_agent)

    return create_sandbox_app(
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        bearer_token="replace-me",
    )


app = build_worker_app()


async def run_control_plane(base_url: str = "http://127.0.0.1:8000") -> None:
    tool_registry = ToolRegistry()
    tool_registry.register(control_plane_draft)

    flow = RemoteReviewFlow(
        tool_registry=tool_registry,
        containment_mode="strict_remote",
        remote_execution_adapter=HTTPSandboxExecutionAdapter(
            base_url=base_url,
            bearer_token="replace-me",
        ),
    )
    state = await flow.run(PromptIn(text="Summarize the incident status in one sentence."))
    print(state.artifacts["review"])


if __name__ == "__main__":
    asyncio.run(run_control_plane())
