from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from governai import Command, IllegalTransitionError, ReducerRegistry, Workflow, route_to, step, tool


class InModel(BaseModel):
    value: int


class OutModel(BaseModel):
    value: int


class AnyPayload(BaseModel):
    model_config = {"extra": "allow"}


@tool(name="cmd.router", input_model=InModel, output_model=Command)
async def router(ctx, data: InModel) -> Command:  # noqa: ARG001
    return Command(goto="second", output={"next_step": "first"})


@tool(name="cmd.first", input_model=AnyPayload, output_model=OutModel)
async def first(ctx, data: AnyPayload) -> OutModel:  # noqa: ARG001
    return OutModel(value=1)


@tool(name="cmd.second", input_model=AnyPayload, output_model=OutModel)
async def second(ctx, data: AnyPayload) -> OutModel:  # noqa: ARG001
    return OutModel(value=2)


@tool(name="cmd.bad", input_model=InModel, output_model=Command)
async def bad_goto(ctx, data: InModel) -> Command:  # noqa: ARG001
    return Command(goto="illegal", output={"value": data.value})


@tool(name="cmd.channels", input_model=InModel, output_model=Command)
async def update_channels(ctx, data: InModel) -> Command:  # noqa: ARG001
    return Command(
        state_update={
            "profile": {"name": "alice"},
            "events": {"event": data.value},
            "cache": True,
            "items": [1],
        },
        output={"next_step": "end"},
    )


class GotoFlow(Workflow[InModel, OutModel]):
    decide = step("decide", tool=router).route_to(allowed=["first", "second", "end"])
    first = step("first", tool=first).then_end()
    second = step("second", tool=second).then_end()


class BadGotoFlow(Workflow[InModel, OutModel]):
    first = step("first", tool=bad_goto).then("second")
    second = step("second", tool=second).then_end()


class ChannelFlow(Workflow[InModel, OutModel]):
    first = step("first", tool=update_channels).route_to(allowed=["end"])
    end = step("end", tool=second).then_end()


@tool(name="cmd.sum", input_model=InModel, output_model=Command)
async def sum_update(ctx, data: InModel) -> Command:  # noqa: ARG001
    return Command(state_update={"score": data.value}, output={"next_step": "end"})


class CustomReducerFlow(Workflow[InModel, OutModel]):
    first = step("first", tool=sum_update).route_to(allowed=["end"])
    end = step("end", tool=second).then_end()


def test_command_goto_overrides_route_payload() -> None:
    async def run() -> None:
        flow = GotoFlow()
        state = await flow.run(InModel(value=1))
        assert state.status.value == "COMPLETED"
        assert state.completed_steps == ["decide", "second"]

    asyncio.run(run())


def test_command_goto_validation_enforced() -> None:
    async def run() -> None:
        flow = BadGotoFlow()
        with pytest.raises(IllegalTransitionError):
            await flow.run(InModel(value=1))

    asyncio.run(run())


def test_builtin_reducers_apply_updates() -> None:
    async def run() -> None:
        flow = ChannelFlow(
            channel_reducers={
                "profile": "merge",
                "events": "append",
                "cache": "clear",
                "items": "prune",
            },
            channel_defaults={
                "profile": {"role": "agent"},
                "events": [],
                "cache": {"x": 1},
                "items": [10, 20, 30],
            },
        )
        state = await flow.run(InModel(value=5))
        assert state.channels["profile"] == {"role": "agent", "name": "alice"}
        assert state.channels["events"] == [{"event": 5}]
        assert state.channels["cache"] is None
        assert state.channels["items"] == [10, 30]

    asyncio.run(run())


def test_custom_reducer_registration() -> None:
    async def run() -> None:
        registry = ReducerRegistry()
        registry.register("sum", lambda current, update: int(current or 0) + int(update))
        flow = CustomReducerFlow(
            reducer_registry=registry,
            channel_reducers={"score": "sum"},
            channel_defaults={"score": 2},
        )
        state = await flow.run(InModel(value=4))
        assert state.channels["score"] == 6

    asyncio.run(run())
