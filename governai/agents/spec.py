"""Serializable agent descriptor model, schema references, and model registry protocol."""

from __future__ import annotations

import warnings
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from governai.tools.base import ExecutionPlacement


with warnings.catch_warnings():
    warnings.simplefilter("ignore", UserWarning)

    class ModelSchemaRef(BaseModel):
        """Reference to a Pydantic model by name and its JSON schema dict."""

        name: str
        schema: dict[str, Any]


@runtime_checkable
class ModelRegistry(Protocol):
    """Protocol for resolving Pydantic model classes by name."""

    def resolve(self, name: str) -> type[BaseModel]: ...


class AgentSpec(BaseModel):
    """Serializable descriptor for an Agent, containing all non-callable fields.

    Enables Zeroth Studio to store, transmit, and reconstruct agent definitions
    without Python callables.
    """

    name: str
    description: str
    instruction: str
    version: str = "0.0.0"
    schema_fingerprint: str | None = None
    input_model: ModelSchemaRef
    output_model: ModelSchemaRef
    allowed_tools: list[str]
    allowed_handoffs: list[str]
    max_turns: int = 1
    max_tool_calls: int = 1
    tags: list[str] = []
    requires_approval: bool = False
    capabilities: list[str] = []
    side_effect: bool = False
    executor_type: str = "agent"
    execution_placement: ExecutionPlacement = "local_only"
    remote_name: str | None = None
