"""Tests for AgentSpec, ModelSchemaRef, ModelRegistry, and Agent.to_spec()/from_spec()."""

from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import BaseModel

from governai.agents.base import Agent
from governai.agents.spec import AgentSpec, ModelRegistry, ModelSchemaRef


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class SampleInput(BaseModel):
    question: str


class SampleOutput(BaseModel):
    answer: str


async def mock_handler(ctx, task):
    pass


class SimpleModelRegistry:
    """A trivial ModelRegistry implementation for testing."""

    def __init__(self):
        self._models: dict[str, type[BaseModel]] = {}

    def register(self, model: type[BaseModel]) -> None:
        self._models[model.__name__] = model

    def resolve(self, name: str) -> type[BaseModel]:
        return self._models[name]


def _make_agent(**overrides) -> Agent:
    defaults = dict(
        name="test-agent",
        description="A test agent",
        instruction="Do stuff",
        handler=mock_handler,
        input_model=SampleInput,
        output_model=SampleOutput,
        allowed_tools=["tool-a"],
        allowed_handoffs=["agent-b"],
        max_turns=3,
        max_tool_calls=5,
        tags=["demo"],
        requires_approval=True,
        capabilities=["cap-1"],
        side_effect=True,
        execution_placement="remote_only",
        remote_name="remote-test",
    )
    defaults.update(overrides)
    return Agent(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAgentSpecFields:
    def test_agent_spec_has_all_non_callable_fields(self):
        spec = AgentSpec(
            name="a",
            description="d",
            instruction="i",
            version="1.0.0",
            schema_fingerprint="abc123",
            input_model=ModelSchemaRef(name="In", schema={"type": "object"}),
            output_model=ModelSchemaRef(name="Out", schema={"type": "object"}),
            allowed_tools=["t1"],
            allowed_handoffs=["h1"],
            max_turns=2,
            max_tool_calls=4,
            tags=["tag"],
            requires_approval=True,
            capabilities=["cap"],
            side_effect=True,
            executor_type="agent",
            execution_placement="remote_only",
            remote_name="r",
        )
        assert spec.name == "a"
        assert spec.description == "d"
        assert spec.instruction == "i"
        assert spec.version == "1.0.0"
        assert spec.schema_fingerprint == "abc123"
        assert spec.input_model.name == "In"
        assert spec.output_model.name == "Out"
        assert spec.allowed_tools == ["t1"]
        assert spec.allowed_handoffs == ["h1"]
        assert spec.max_turns == 2
        assert spec.max_tool_calls == 4
        assert spec.tags == ["tag"]
        assert spec.requires_approval is True
        assert spec.capabilities == ["cap"]
        assert spec.side_effect is True
        assert spec.executor_type == "agent"
        assert spec.execution_placement == "remote_only"
        assert spec.remote_name == "r"

    def test_agent_spec_version_defaults_to_000(self):
        spec = AgentSpec(
            name="a",
            description="d",
            instruction="i",
            input_model=ModelSchemaRef(name="In", schema={}),
            output_model=ModelSchemaRef(name="Out", schema={}),
            allowed_tools=[],
            allowed_handoffs=[],
        )
        assert spec.version == "0.0.0"


class TestModelSchemaRef:
    def test_model_schema_ref_stores_name_and_schema(self):
        ref = ModelSchemaRef(name="MyModel", schema={"type": "object"})
        assert ref.name == "MyModel"
        assert ref.schema == {"type": "object"}


class TestAgentSpecJsonRoundTrip:
    def test_agent_spec_json_round_trip(self):
        spec = AgentSpec(
            name="rt",
            description="round-trip",
            instruction="go",
            version="2.1.0",
            schema_fingerprint="deadbeef",
            input_model=ModelSchemaRef(name="In", schema={"type": "object", "properties": {"q": {"type": "string"}}}),
            output_model=ModelSchemaRef(name="Out", schema={"type": "object", "properties": {"a": {"type": "string"}}}),
            allowed_tools=["x"],
            allowed_handoffs=["y"],
            max_turns=5,
            max_tool_calls=10,
            tags=["t1", "t2"],
            requires_approval=False,
            capabilities=["c1"],
            side_effect=False,
            executor_type="agent",
            execution_placement="local_only",
            remote_name=None,
        )
        json_str = spec.model_dump_json()
        spec2 = AgentSpec.model_validate_json(json_str)
        assert spec2.model_dump() == spec.model_dump()


class TestAgentToSpec:
    def test_agent_to_spec_extracts_all_fields(self):
        agent = _make_agent()
        spec = agent.to_spec()

        assert isinstance(spec, AgentSpec)
        assert spec.name == "test-agent"
        assert spec.description == "A test agent"
        assert spec.instruction == "Do stuff"
        assert spec.version == "0.0.0"
        assert spec.input_model.name == "SampleInput"
        assert spec.output_model.name == "SampleOutput"
        assert spec.input_model.schema == SampleInput.model_json_schema()
        assert spec.output_model.schema == SampleOutput.model_json_schema()
        assert spec.allowed_tools == ["tool-a"]
        assert spec.allowed_handoffs == ["agent-b"]
        assert spec.max_turns == 3
        assert spec.max_tool_calls == 5
        assert spec.tags == ["demo"]
        assert spec.requires_approval is True
        assert spec.capabilities == ["cap-1"]
        assert spec.side_effect is True
        assert spec.executor_type == "agent"
        assert spec.execution_placement == "remote_only"
        assert spec.remote_name == "remote-test"
        # fingerprint is 32-char hex
        assert isinstance(spec.schema_fingerprint, str)
        assert len(spec.schema_fingerprint) == 32

    def test_agent_to_spec_computes_fingerprint(self):
        agent = _make_agent()
        spec = agent.to_spec()

        input_schema = SampleInput.model_json_schema()
        output_schema = SampleOutput.model_json_schema()
        combined = json.dumps({"input": input_schema, "output": output_schema}, sort_keys=True).encode()
        expected = hashlib.blake2b(combined, digest_size=16).hexdigest()

        assert spec.schema_fingerprint == expected


class TestAgentFromSpec:
    def test_agent_from_spec_round_trip(self):
        agent = _make_agent()
        spec = agent.to_spec()

        registry = SimpleModelRegistry()
        registry.register(SampleInput)
        registry.register(SampleOutput)

        agent2 = Agent.from_spec(spec, mock_handler, registry)

        assert agent2.name == agent.name
        assert agent2.description == agent.description
        assert agent2.instruction == agent.instruction
        assert agent2.max_turns == agent.max_turns
        assert agent2.max_tool_calls == agent.max_tool_calls
        assert agent2.tags == agent.tags
        assert agent2.requires_approval == agent.requires_approval
        assert agent2.capabilities == agent.capabilities
        assert agent2.side_effect == agent.side_effect
        assert agent2.execution_placement == agent.execution_placement
        assert agent2.remote_name == agent.remote_name
        assert agent2.input_model is SampleInput
        assert agent2.output_model is SampleOutput

    def test_agent_from_spec_raises_without_registry(self):
        agent = _make_agent()
        spec = agent.to_spec()

        with pytest.raises(ValueError, match="ModelRegistry required"):
            Agent.from_spec(spec, mock_handler, registry=None)


class TestModelRegistryProtocol:
    def test_model_registry_protocol_is_runtime_checkable(self):
        registry = SimpleModelRegistry()
        assert isinstance(registry, ModelRegistry)
