from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from governai import RoutingResolutionError, Workflow, step, tool


class InModel(BaseModel):
    next_step: str


class RouteOut(BaseModel):
    next_step: str


class OutModel(BaseModel):
    done: bool


@tool(name="route.decide", input_model=InModel, output_model=RouteOut)
async def decide(ctx, data: InModel) -> RouteOut:
    return RouteOut(next_step=data.next_step)


@tool(name="route.docs", input_model=RouteOut, output_model=OutModel)
async def docs(ctx, data: RouteOut) -> OutModel:
    return OutModel(done=True)


@tool(name="route.human", input_model=RouteOut, output_model=OutModel)
async def human(ctx, data: RouteOut) -> OutModel:
    return OutModel(done=True)


class RouteFlow(Workflow[InModel, OutModel]):
    decide = step("decide", tool=decide).route_to(allowed=["docs", "human", "end"])
    docs = step("docs", tool=docs).then_end()
    human = step("human", tool=human).then_end()


def test_bounded_routing_valid_path() -> None:
    async def run() -> None:
        flow = RouteFlow()
        state = await flow.run(InModel(next_step="docs"))
        assert state.completed_steps == ["decide", "docs"]

    asyncio.run(run())


def test_bounded_routing_invalid_path_rejected() -> None:
    async def run() -> None:
        flow = RouteFlow()
        with pytest.raises(RoutingResolutionError):
            await flow.run(InModel(next_step="evil"))

    asyncio.run(run())
