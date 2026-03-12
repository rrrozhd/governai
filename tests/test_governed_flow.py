from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from governai import (
    GovernedFlowSpec,
    GovernedStepSpec,
    InMemoryRunStore,
    PolicyDecision,
    PolicyDeniedError,
    ThreadPoolBackend,
    branch,
    end,
    governed_flow,
    then,
    tool,
)


class InModel(BaseModel):
    value: int


class MidModel(BaseModel):
    value: int


class RouteModel(BaseModel):
    value: int
    route: str


class OutModel(BaseModel):
    value: int


@tool(name="gov.add", input_model=InModel, output_model=MidModel)
def add_one(ctx, data: InModel) -> MidModel:  # noqa: ARG001
    return MidModel(value=data.value + 1)


@tool(name="gov.branch", input_model=MidModel, output_model=RouteModel)
async def classify(ctx, data: MidModel) -> RouteModel:  # noqa: ARG001
    route = "even" if data.value % 2 == 0 else "odd"
    return RouteModel(value=data.value, route=route)


@tool(name="gov.even", input_model=RouteModel, output_model=OutModel)
async def handle_even(ctx, data: RouteModel) -> OutModel:  # noqa: ARG001
    return OutModel(value=data.value * 10)


@tool(name="gov.odd", input_model=RouteModel, output_model=OutModel)
async def handle_odd(ctx, data: RouteModel) -> OutModel:  # noqa: ARG001
    return OutModel(value=data.value * 100)


def deny_all(ctx) -> PolicyDecision:
    return PolicyDecision(allow=False, reason="blocked")


def test_governed_flow_strict_and_branching() -> None:
    async def run() -> None:
        spec = GovernedFlowSpec(
            name="calc_flow",
            steps=[
                GovernedStepSpec(name="first", tool=add_one, transition=then("decide")),
                GovernedStepSpec(
                    name="decide",
                    tool=classify,
                    transition=branch(router="route", mapping={"even": "even", "odd": "odd"}),
                ),
                GovernedStepSpec(name="even", tool=handle_even, transition=end()),
                GovernedStepSpec(name="odd", tool=handle_odd, transition=end()),
            ],
        )

        flow = governed_flow(spec)
        state = await flow.run(InModel(value=1))
        assert state.status.value == "COMPLETED"
        assert state.artifacts["even"]["value"] == 20

    asyncio.run(run())


def test_governed_flow_with_thread_backend_and_run_store() -> None:
    async def run() -> None:
        store = InMemoryRunStore()
        spec = GovernedFlowSpec(
            name="simple_flow",
            steps=[
                GovernedStepSpec(name="first", tool=add_one, transition=end()),
            ],
        )
        flow = governed_flow(spec, run_store=store, execution_backend=ThreadPoolBackend())
        state = await flow.run(InModel(value=2))
        assert state.status.value == "COMPLETED"
        persisted = await store.get(state.run_id)
        assert persisted is not None
        assert persisted.status.value == "COMPLETED"

    asyncio.run(run())


def test_governed_flow_policy_from_spec() -> None:
    async def run() -> None:
        spec = GovernedFlowSpec(
            name="policy_flow",
            policies=[deny_all],
            steps=[GovernedStepSpec(name="first", tool=add_one, transition=end())],
        )
        flow = governed_flow(spec)
        with pytest.raises(PolicyDeniedError):
            await flow.run(InModel(value=1))

    asyncio.run(run())
