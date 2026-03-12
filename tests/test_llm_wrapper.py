from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from governai import GovernedLLM


@dataclass
class FakeAIMessage:
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class FakeModel:
    def __init__(self) -> None:
        self.bound_args: dict[str, Any] = {}
        self.bound_tools: list[Any] = []

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "FakeModel":
        nxt = FakeModel()
        nxt.bound_tools = list(tools)
        nxt.bound_args = dict(kwargs)
        return nxt

    def invoke(self, messages: Any, **kwargs: Any) -> FakeAIMessage:  # noqa: ARG002
        return FakeAIMessage(
            content="ok",
            tool_calls=[{"id": "t1", "name": "demo", "args": {"value": 1}}],
        )

    async def ainvoke(self, messages: Any, **kwargs: Any) -> FakeAIMessage:  # noqa: ARG002
        return self.invoke(messages, **kwargs)


def test_governed_llm_bind_tools_and_invoke() -> None:
    base = GovernedLLM(FakeModel())
    bound = base.bind_tools([{"name": "demo"}], tool_choice="auto")
    assert bound.model.bound_args["tool_choice"] == "auto"
    response = bound.invoke([{"role": "user", "content": "hi"}])
    assert response.content == "ok"
    assert response.tool_calls[0]["name"] == "demo"


def test_governed_llm_ainvoke() -> None:
    async def run() -> None:
        llm = GovernedLLM(FakeModel())
        response = await llm.ainvoke([{"role": "user", "content": "go"}])
        assert response.tool_calls[0]["id"] == "t1"

    asyncio.run(run())

