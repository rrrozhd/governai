from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from governai import (
    AgentRegistry,
    DSLAst,
    DSLSemanticError,
    DSLSyntaxError,
    ToolRegistry,
    dsl_to_flow_config,
    governed_flow_from_config,
    governed_flow_from_dsl,
    parse_dsl,
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


def _tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for registered in [add_one, classify, handle_even, handle_odd]:
        registry.register(registered)
    return registry


def _dsl_text() -> str:
    return """
flow calc_flow {
  entry: first;
  channel profile reducer merge initial {"role": "agent"};
  interrupts ttl 120 max_pending 2;
  step first: tool gov.add -> decide;
  step decide: tool gov.branch branch router route mapping {"even": even, "odd": odd};
  step even: tool gov.even -> end;
  step odd: tool gov.odd -> end;
}
"""


def _config_payload() -> dict:
    return {
        "version": "v1",
        "name": "calc_flow",
        "entry_step": "first",
        "channels": [{"name": "profile", "reducer": "merge", "initial": {"role": "agent"}}],
        "interrupts": {"ttl_seconds": 120, "max_pending": 2},
        "steps": [
            {"name": "first", "tool": "gov.add", "transition": {"kind": "then", "next_step": "decide"}},
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


def test_parse_dsl_to_ast_and_config() -> None:
    ast = parse_dsl(_dsl_text())
    assert isinstance(ast, DSLAst)
    assert ast.flow.name == "calc_flow"
    assert ast.flow.entry_step == "first"
    assert ast.flow.channels[0].initial == {"role": "agent"}

    config = dsl_to_flow_config(_dsl_text())
    assert config.steps[1].transition.kind == "branch"
    assert config.steps[1].transition.mapping == {"even": "even", "odd": "odd"}


def test_governed_flow_from_dsl_matches_config_behavior() -> None:
    async def run() -> None:
        registry = _tool_registry()
        dsl_flow = governed_flow_from_dsl(
            _dsl_text(),
            tool_registry=registry,
            agent_registry=AgentRegistry(),
        )
        config_flow = governed_flow_from_config(
            _config_payload(),
            tool_registry=registry,
            agent_registry=AgentRegistry(),
        )

        dsl_state = await dsl_flow.run(InModel(value=1))
        cfg_state = await config_flow.run(InModel(value=1))
        assert dsl_state.status.value == "COMPLETED"
        assert cfg_state.status.value == "COMPLETED"
        assert dsl_state.completed_steps == cfg_state.completed_steps
        assert dsl_state.artifacts["even"]["value"] == cfg_state.artifacts["even"]["value"]

    asyncio.run(run())


def test_dsl_syntax_error_has_source_coordinates() -> None:
    bad = """
flow broken {
  step first: tool gov.add ->;
}
"""
    with pytest.raises(DSLSyntaxError) as exc:
        parse_dsl(bad)
    assert exc.value.line is not None
    assert exc.value.column is not None


def test_dsl_semantic_error_has_source_coordinates() -> None:
    bad = """
flow broken {
  entry: first;
  step first: tool gov.add -> missing;
}
"""
    with pytest.raises(DSLSemanticError) as exc:
        parse_dsl(bad)
    assert exc.value.line is not None
    assert exc.value.column is not None


def test_governed_flow_from_dsl_unknown_tool_is_source_mapped() -> None:
    bad = """
flow broken {
  step first: tool missing.tool -> end;
}
"""
    with pytest.raises(DSLSemanticError) as exc:
        governed_flow_from_dsl(
            bad,
            tool_registry=_tool_registry(),
            agent_registry=AgentRegistry(),
        )
    assert "Unknown tool" in str(exc.value)
    assert exc.value.line is not None
