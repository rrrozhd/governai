from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from governai import ToolValidationError, tool


class InModel(BaseModel):
    value: int


class OutModel(BaseModel):
    doubled: int


@tool(name="math.double", input_model=InModel, output_model=OutModel)
async def double_tool(ctx, data: InModel) -> OutModel:
    return OutModel(doubled=data.value * 2)


@tool(name="math.bad", input_model=InModel, output_model=OutModel)
async def bad_output_tool(ctx, data: InModel):
    return {"bad": "shape"}


def test_python_tool_validates_input_and_output_success() -> None:
    async def run() -> None:
        out = await double_tool.execute(None, {"value": 3})
        assert out.doubled == 6

    asyncio.run(run())


def test_python_tool_input_validation_error() -> None:
    async def run() -> None:
        with pytest.raises(ToolValidationError):
            await double_tool.execute(None, {"value": "x"})

    asyncio.run(run())


def test_python_tool_output_validation_error() -> None:
    async def run() -> None:
        with pytest.raises(ToolValidationError):
            await bad_output_tool.execute(None, {"value": 2})

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Contract versioning tests (01-03)
# ---------------------------------------------------------------------------

from governai.tools.base import Tool
from governai.tools.registry import ToolRegistry
from governai.app.spec import GovernedStepSpec


class TestInput(BaseModel):
    value: int


class TestOutput(BaseModel):
    result: str


class DifferentInput(BaseModel):
    name: str
    count: int


def test_tool_version_field_default() -> None:
    t = Tool(name="t", input_model=TestInput, output_model=TestOutput)
    assert t.version == "0.0.0"


def test_tool_version_field_explicit() -> None:
    t = Tool(name="t", version="1.2.3", input_model=TestInput, output_model=TestOutput)
    assert t.version == "1.2.3"


def test_governed_step_spec_version_default() -> None:
    s = GovernedStepSpec(name="s")
    assert s.version == "0.0.0"


def test_governed_step_spec_version_explicit() -> None:
    s = GovernedStepSpec(name="s", version="2.0.0")
    assert s.version == "2.0.0"


def test_tool_registry_versioned_key() -> None:
    registry = ToolRegistry()
    t1 = Tool(name="calc", version="1.0.0", input_model=TestInput, output_model=TestOutput, remote_name="calc-v1")
    t2 = Tool(name="calc", version="2.0.0", input_model=TestInput, output_model=TestOutput, remote_name="calc-v2")
    registry.register(t1)
    registry.register(t2)
    assert registry.get("calc", "1.0.0").version == "1.0.0"
    assert registry.get("calc", "2.0.0").version == "2.0.0"


def test_tool_registry_get_default_version() -> None:
    registry = ToolRegistry()
    t = Tool(name="calc", input_model=TestInput, output_model=TestOutput)
    registry.register(t)
    assert registry.get("calc").version == "0.0.0"


def test_tool_registry_has_with_version() -> None:
    registry = ToolRegistry()
    t = Tool(name="calc", version="1.0.0", input_model=TestInput, output_model=TestOutput)
    registry.register(t)
    assert registry.has("calc", "1.0.0") is True
    assert registry.has("calc", "9.9.9") is False


def test_tool_schema_fingerprint_set_on_register() -> None:
    registry = ToolRegistry()
    t = Tool(name="fp", input_model=TestInput, output_model=TestOutput)
    assert t.schema_fingerprint is None
    registry.register(t)
    assert t.schema_fingerprint is not None
    assert len(t.schema_fingerprint) == 32
    assert all(c in "0123456789abcdef" for c in t.schema_fingerprint)


def test_tool_schema_fingerprint_deterministic() -> None:
    registry = ToolRegistry()
    t1 = Tool(name="a", version="1.0.0", input_model=TestInput, output_model=TestOutput)
    t2 = Tool(name="b", version="1.0.0", input_model=TestInput, output_model=TestOutput)
    registry.register(t1)
    registry.register(t2)
    assert t1.schema_fingerprint == t2.schema_fingerprint


def test_tool_schema_fingerprint_differs_for_different_schemas() -> None:
    registry = ToolRegistry()
    t1 = Tool(name="x", input_model=TestInput, output_model=TestOutput)
    t2 = Tool(name="y", input_model=DifferentInput, output_model=TestOutput)
    registry.register(t1)
    registry.register(t2)
    assert t1.schema_fingerprint != t2.schema_fingerprint
