from __future__ import annotations

import asyncio
import json

from pydantic import BaseModel

from governai import GovernedToolCallLoop, Workflow, extract_tool_calls, step, tool


class InModel(BaseModel):
    value: int


class OutModel(BaseModel):
    value: int


@tool(name="tc.double", input_model=InModel, output_model=OutModel)
async def double(ctx, data: InModel) -> OutModel:  # noqa: ARG001
    return OutModel(value=data.value * 2)


class ToolCallFlow(Workflow[InModel, OutModel]):
    only = step("only", tool=double).then_end()


def _message_content(value: object) -> str:
    content = getattr(value, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(value, dict):
        maybe = value.get("content")
        if isinstance(maybe, str):
            return maybe
    return str(value)


def test_extract_tool_calls_normalizes_args() -> None:
    message = {
        "tool_calls": [
            {"id": "a", "name": "x", "args": {"value": 1}},
            {"id": "b", "name": "y", "args": "{\"value\":2}"},
        ]
    }
    calls = extract_tool_calls(message)
    assert calls[0]["args"] == {"value": 1}
    assert calls[1]["args"] == {"value": 2}


def test_governed_tool_call_loop_executes_tools() -> None:
    async def run() -> None:
        flow = ToolCallFlow()
        state = await flow.run(InModel(value=1))
        loop = GovernedToolCallLoop()
        ai_message = {"tool_calls": [{"id": "call-1", "name": "tc.double", "args": {"value": 5}}]}
        messages = await loop.execute_once(
            runtime=flow.runtime,
            workflow=flow,
            state=state,
            step_name="tool_loop",
            ai_message=ai_message,
        )
        assert len(messages) == 1
        payload = json.loads(_message_content(messages[0]))
        assert payload["value"] == 10

    asyncio.run(run())

