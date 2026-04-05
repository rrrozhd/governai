"""Tests for ToolManifest and Tool.to_manifest()."""

from __future__ import annotations

import json

from pydantic import BaseModel

from governai.tools.base import Tool


class ToolInput(BaseModel):
    query: str


class ToolOutput(BaseModel):
    result: str


class EchoTool(Tool[ToolInput, ToolOutput]):
    """Concrete Tool subclass for testing."""

    async def _execute_validated(self, ctx, data: ToolInput) -> dict:
        return {"result": data.query}


def _make_tool(**overrides) -> EchoTool:
    defaults = dict(
        name="echo",
        version="1.0.0",
        description="Echo tool",
        input_model=ToolInput,
        output_model=ToolOutput,
        capabilities=["read", "write"],
        side_effect=True,
        timeout_seconds=30.0,
        requires_approval=True,
        tags=["test", "echo"],
        executor_type="python",
        execution_placement="local_or_remote",
        remote_name="echo-remote",
    )
    defaults.update(overrides)
    return EchoTool(**defaults)


class TestToolManifestModel:
    """Tests for ToolManifest Pydantic model (MFST-01)."""

    def test_tool_manifest_has_all_data_fields(self):
        """ToolManifest accepts all Tool data fields (D-08, MFST-01)."""
        from governai.tools.manifest import ToolManifest

        manifest = ToolManifest(
            name="echo",
            version="1.0.0",
            description="Echo tool",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            schema_fingerprint="abc123",
            capabilities=["read", "write"],
            side_effect=True,
            timeout_seconds=30.0,
            requires_approval=True,
            tags=["test"],
            executor_type="python",
            execution_placement="local_or_remote",
            remote_name="echo-remote",
        )
        assert manifest.name == "echo"
        assert manifest.version == "1.0.0"
        assert manifest.description == "Echo tool"
        assert manifest.input_schema == {"type": "object"}
        assert manifest.output_schema == {"type": "object"}
        assert manifest.schema_fingerprint == "abc123"
        assert manifest.capabilities == ["read", "write"]
        assert manifest.side_effect is True
        assert manifest.timeout_seconds == 30.0
        assert manifest.requires_approval is True
        assert manifest.tags == ["test"]
        assert manifest.executor_type == "python"
        assert manifest.execution_placement == "local_or_remote"
        assert manifest.remote_name == "echo-remote"

    def test_tool_manifest_version_defaults_to_000(self):
        """ToolManifest defaults version to '0.0.0'."""
        from governai.tools.manifest import ToolManifest

        manifest = ToolManifest(
            name="t",
            input_schema={},
            output_schema={},
        )
        assert manifest.version == "0.0.0"

    def test_tool_manifest_json_round_trip(self):
        """ToolManifest survives JSON serialization round-trip."""
        from governai.tools.manifest import ToolManifest

        manifest = ToolManifest(
            name="echo",
            version="2.0.0",
            description="Round trip test",
            input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"r": {"type": "string"}}},
            schema_fingerprint="deadbeef",
            capabilities=["search"],
            side_effect=False,
            timeout_seconds=10.0,
            requires_approval=False,
            tags=["round-trip"],
            executor_type="python",
            execution_placement="remote_only",
            remote_name="echo-v2",
        )
        json_str = manifest.model_dump_json()
        restored = ToolManifest.model_validate_json(json_str)
        assert restored.model_dump() == manifest.model_dump()

    def test_tool_manifest_no_reconstruction(self):
        """ToolManifest has no from_manifest or to_tool method (D-09)."""
        from governai.tools.manifest import ToolManifest

        assert not hasattr(ToolManifest, "from_manifest")
        assert not hasattr(ToolManifest, "to_tool")

    def test_tool_manifest_usable_for_capability_check(self):
        """ToolManifest.capabilities is accessible without a live Tool (D-10)."""
        from governai.tools.manifest import ToolManifest

        manifest = ToolManifest(
            name="checker",
            input_schema={},
            output_schema={},
            capabilities=["read", "write", "delete"],
        )
        assert "read" in manifest.capabilities
        assert "delete" in manifest.capabilities
        assert len(manifest.capabilities) == 3


class TestToolToManifest:
    """Tests for Tool.to_manifest() (MFST-02, MFST-03)."""

    def test_tool_to_manifest_extracts_all_fields(self):
        """Tool.to_manifest() returns ToolManifest with all fields matching."""
        tool = _make_tool()
        manifest = tool.to_manifest()

        assert manifest.name == "echo"
        assert manifest.version == "1.0.0"
        assert manifest.description == "Echo tool"
        assert manifest.input_schema == ToolInput.model_json_schema()
        assert manifest.output_schema == ToolOutput.model_json_schema()
        assert manifest.capabilities == ["read", "write"]
        assert manifest.side_effect is True
        assert manifest.timeout_seconds == 30.0
        assert manifest.requires_approval is True
        assert manifest.tags == ["test", "echo"]
        assert manifest.executor_type == "python"
        assert manifest.execution_placement == "local_or_remote"
        assert manifest.remote_name == "echo-remote"

    def test_tool_to_manifest_computes_fingerprint_when_none(self):
        """Unregistered Tool (schema_fingerprint=None) gets inline fingerprint."""
        tool = _make_tool()
        assert tool.schema_fingerprint is None

        manifest = tool.to_manifest()
        assert manifest.schema_fingerprint is not None
        assert len(manifest.schema_fingerprint) == 32
        assert all(c in "0123456789abcdef" for c in manifest.schema_fingerprint)

    def test_tool_to_manifest_uses_existing_fingerprint(self):
        """Registered Tool (schema_fingerprint set) uses existing fingerprint."""
        tool = _make_tool()
        tool.schema_fingerprint = "existing1234567890abcdef12345678"

        manifest = tool.to_manifest()
        assert manifest.schema_fingerprint == "existing1234567890abcdef12345678"

    def test_tool_to_manifest_computed_fingerprint_is_deterministic(self):
        """Same Tool produces the same fingerprint on repeated calls."""
        tool = _make_tool()
        m1 = tool.to_manifest()
        m2 = tool.to_manifest()
        assert m1.schema_fingerprint == m2.schema_fingerprint
