from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import BaseModel

from governai import (
    AgentRegistry,
    FlowConfigV1,
    InMemoryRunStore,
    PolicyDeniedError,
    Skill,
    SkillRegistry,
    ThreadPoolBackend,
    ToolRegistry,
    UnknownPolicyError,
    UnknownToolError,
    governed_flow_from_config,
    load_flow_config,
    tool,
    validate_flow_config,
)
from governai.app.config import InvalidTransitionError
from governai.models.policy import PolicyDecision


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


def _tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for registered in [add_one, classify, handle_even, handle_odd]:
        registry.register(registered)
    return registry


def _base_flow_payload() -> dict:
    return {
        "version": "v1",
        "name": "calc_flow",
        "entry_step": "first",
        "channels": [{"name": "profile", "reducer": "merge", "initial": {"role": "agent"}}],
        "interrupts": {"ttl_seconds": 120, "max_pending": 2},
        "steps": [
            {
                "name": "first",
                "tool": "gov.add",
                "transition": {"kind": "then", "next_step": "decide"},
            },
            {
                "name": "decide",
                "tool": "gov.branch",
                "transition": {
                    "kind": "branch",
                    "router": "route",
                    "mapping": {"even": "even", "odd": "odd"},
                },
            },
            {"name": "even", "tool": "gov.even", "transition": {"kind": "end"}},
            {"name": "odd", "tool": "gov.odd", "transition": {"kind": "end"}},
        ],
    }


def test_load_flow_config_yaml_and_json(tmp_path) -> None:
    payload = _base_flow_payload()
    yaml_path = tmp_path / "flow.yaml"
    yaml_path.write_text(
        """
version: v1
name: calc_flow
entry_step: first
channels:
  - name: profile
    reducer: merge
    initial:
      role: agent
interrupts:
  ttl_seconds: 120
  max_pending: 2
steps:
  - name: first
    tool: gov.add
    transition:
      kind: then
      next_step: decide
  - name: decide
    tool: gov.branch
    transition:
      kind: branch
      router: route
      mapping:
        even: even
        odd: odd
  - name: even
    tool: gov.even
    transition:
      kind: end
  - name: odd
    tool: gov.odd
    transition:
      kind: end
""".strip(),
        encoding="utf-8",
    )
    json_path = tmp_path / "flow.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    yaml_config = load_flow_config(yaml_path)
    json_config = load_flow_config(json_path)
    assert isinstance(yaml_config, FlowConfigV1)
    assert yaml_config.name == "calc_flow"
    assert json_config.name == "calc_flow"
    assert json_config.interrupts.max_pending == 2


def test_governed_flow_from_config_runs() -> None:
    async def run() -> None:
        flow = governed_flow_from_config(
            _base_flow_payload(),
            tool_registry=_tool_registry(),
            agent_registry=AgentRegistry(),
            runtime_overrides={
                "run_store": InMemoryRunStore(),
                "execution_backend": ThreadPoolBackend(),
            },
        )
        state = await flow.run(InModel(value=1))
        assert state.status.value == "COMPLETED"
        assert state.artifacts["even"]["value"] == 20
        assert state.channels["profile"] == {"role": "agent"}

    asyncio.run(run())


def test_unknown_tool_reference_fails_preflight() -> None:
    payload = _base_flow_payload()
    payload["steps"][0]["tool"] = "missing.tool"
    with pytest.raises(UnknownToolError):
        governed_flow_from_config(
            payload,
            tool_registry=_tool_registry(),
            agent_registry=AgentRegistry(),
        )


def test_unknown_policy_reference_fails_preflight() -> None:
    payload = _base_flow_payload()
    payload["policies"] = ["deny_all"]
    with pytest.raises(UnknownPolicyError):
        governed_flow_from_config(
            payload,
            tool_registry=_tool_registry(),
            agent_registry=AgentRegistry(),
        )


def test_invalid_transition_target_fails_validation() -> None:
    payload = _base_flow_payload()
    payload["steps"][0]["transition"]["next_step"] = "missing"
    config = load_flow_config(payload)
    with pytest.raises(InvalidTransitionError):
        validate_flow_config(config)


def test_policy_and_skill_resolution() -> None:
    async def run() -> None:
        payload = _base_flow_payload()
        payload["policies"] = ["deny_all"]
        payload["skills"] = ["core"]
        skill_registry = SkillRegistry()
        skill_registry.register(Skill(name="core", tools=[add_one], description="core skill"))

        flow = governed_flow_from_config(
            payload,
            tool_registry=_tool_registry(),
            agent_registry=AgentRegistry(),
            policy_registry={"deny_all": deny_all},
            skill_registry=skill_registry,
        )
        with pytest.raises(PolicyDeniedError):
            await flow.run(InModel(value=1))

    asyncio.run(run())
