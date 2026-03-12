from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, runtime_checkable

from pydantic import BaseModel, Field, ValidationError, model_validator

from governai.agents.registry import AgentRegistry
from governai.app.flow import GovernedFlow, governed_flow
from governai.app.spec import (
    ChannelSpec,
    GovernedFlowSpec,
    GovernedStepSpec,
    InterruptContract,
    branch,
    end,
    route_to,
    then,
)
from governai.models.common import END_STEP, normalize_step_ref
from governai.skills.registry import SkillRegistry
from governai.tools.registry import ToolRegistry


class FlowConfigError(ValueError):
    """Base error for external flow config handling."""


class FlowConfigLoadError(FlowConfigError):
    """Raised when config input cannot be loaded/parsing fails."""


class FlowConfigValidationError(FlowConfigError):
    """Raised when config fails preflight validation/compilation."""


class UnknownToolError(FlowConfigValidationError):
    def __init__(self, tool_name: str) -> None:
        """Initialize UnknownToolError."""
        super().__init__(f"Unknown tool: {tool_name}")
        self.tool_name = tool_name


class UnknownAgentError(FlowConfigValidationError):
    def __init__(self, agent_name: str) -> None:
        """Initialize UnknownAgentError."""
        super().__init__(f"Unknown agent: {agent_name}")
        self.agent_name = agent_name


class UnknownPolicyError(FlowConfigValidationError):
    def __init__(self, policy_name: str) -> None:
        """Initialize UnknownPolicyError."""
        super().__init__(f"Unknown policy: {policy_name}")
        self.policy_name = policy_name


class UnknownSkillError(FlowConfigValidationError):
    def __init__(self, skill_name: str) -> None:
        """Initialize UnknownSkillError."""
        super().__init__(f"Unknown skill: {skill_name}")
        self.skill_name = skill_name


class DuplicateStepError(FlowConfigValidationError):
    def __init__(self, step_name: str) -> None:
        """Initialize DuplicateStepError."""
        super().__init__(f"Duplicate step name: {step_name}")
        self.step_name = step_name


class UnknownEntryStepError(FlowConfigValidationError):
    def __init__(self, step_name: str) -> None:
        """Initialize UnknownEntryStepError."""
        super().__init__(f"Entry step not found: {step_name}")
        self.step_name = step_name


class InvalidTransitionError(FlowConfigValidationError):
    def __init__(self, step_name: str, message: str) -> None:
        """Initialize InvalidTransitionError."""
        super().__init__(f"Step {step_name} has invalid transition: {message}")
        self.step_name = step_name


class TransitionConfigV1(BaseModel):
    kind: Literal["then", "end", "branch", "route_to"]
    next_step: str | None = None
    router: str | None = None
    mapping: dict[str, str] | None = None
    allowed: list[str] | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> "TransitionConfigV1":
        """Internal helper to validate shape."""
        if self.kind == "then":
            if not self.next_step:
                raise ValueError("then transition requires next_step")
            self.next_step = normalize_step_ref(self.next_step)
            self.router = None
            self.mapping = None
            self.allowed = None
            return self

        if self.kind == "end":
            self.next_step = END_STEP
            self.router = None
            self.mapping = None
            self.allowed = None
            return self

        if self.kind == "branch":
            if not self.router:
                raise ValueError("branch transition requires router")
            if not self.mapping:
                raise ValueError("branch transition requires non-empty mapping")
            self.next_step = None
            self.allowed = None
            self.mapping = {str(key): normalize_step_ref(value) for key, value in self.mapping.items()}
            return self

        if not self.allowed:
            raise ValueError("route_to transition requires non-empty allowed list")
        self.next_step = None
        self.router = None
        self.mapping = None
        self.allowed = [normalize_step_ref(step_name) for step_name in self.allowed]
        return self


class StepConfigV1(BaseModel):
    name: str
    tool: str | None = None
    agent: str | None = None
    required_artifacts: list[str] = Field(default_factory=list)
    emitted_artifact: str | None = None
    approval_override: bool | None = None
    transition: TransitionConfigV1

    @model_validator(mode="after")
    def _validate_executor(self) -> "StepConfigV1":
        """Internal helper to validate executor."""
        if (self.tool is None) == (self.agent is None):
            raise ValueError(f"Step {self.name} must define exactly one of tool/agent")
        return self


class ChannelConfigV1(BaseModel):
    name: str
    reducer: str = "replace"
    initial: Any = None


class InterruptConfigV1(BaseModel):
    ttl_seconds: int = 1800
    max_pending: int = 1


class FlowConfigV1(BaseModel):
    version: Literal["v1"] = "v1"
    name: str
    steps: list[StepConfigV1]
    entry_step: str | None = None
    policies: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    channels: list[ChannelConfigV1] = Field(default_factory=list)
    interrupts: InterruptConfigV1 = Field(default_factory=InterruptConfigV1)


@runtime_checkable
class ToolResolver(Protocol):
    """Resolve tool names to concrete tool executors."""

    def resolve(self, tool_name: str) -> Any:
        """Return the registered tool object for the given tool name."""
        ...


@runtime_checkable
class AgentResolver(Protocol):
    """Resolve agent names to concrete agent executors."""

    def resolve(self, agent_name: str) -> Any:
        """Return the registered agent object for the given agent name."""
        ...


@runtime_checkable
class PolicyResolver(Protocol):
    """Resolve policy names to callable policy functions."""

    def resolve(self, policy_name: str) -> Any:
        """Return the policy function for the given policy name."""
        ...


@runtime_checkable
class SkillResolver(Protocol):
    """Resolve skill names to concrete skill objects."""

    def resolve(self, skill_name: str) -> Any:
        """Return the skill object for the given skill name."""
        ...


class RegistryToolResolver:
    def __init__(self, registry: ToolRegistry) -> None:
        """Initialize RegistryToolResolver."""
        self._registry = registry

    def resolve(self, tool_name: str) -> Any:
        """Resolve."""
        try:
            return self._registry.get(tool_name)
        except KeyError as exc:
            raise UnknownToolError(tool_name) from exc


class RegistryAgentResolver:
    def __init__(self, registry: AgentRegistry) -> None:
        """Initialize RegistryAgentResolver."""
        self._registry = registry

    def resolve(self, agent_name: str) -> Any:
        """Resolve."""
        try:
            return self._registry.get(agent_name)
        except KeyError as exc:
            raise UnknownAgentError(agent_name) from exc


class MappingPolicyResolver:
    def __init__(self, mapping: Mapping[str, Any]) -> None:
        """Initialize MappingPolicyResolver."""
        self._mapping = mapping

    def resolve(self, policy_name: str) -> Any:
        """Resolve."""
        try:
            return self._mapping[policy_name]
        except KeyError as exc:
            raise UnknownPolicyError(policy_name) from exc


class RegistrySkillResolver:
    def __init__(self, registry: SkillRegistry | Mapping[str, Any]) -> None:
        """Initialize RegistrySkillResolver."""
        self._registry = registry

    def resolve(self, skill_name: str) -> Any:
        """Resolve."""
        if isinstance(self._registry, SkillRegistry):
            try:
                return self._registry.get(skill_name)
            except KeyError as exc:
                raise UnknownSkillError(skill_name) from exc
        try:
            return self._registry[skill_name]
        except KeyError as exc:
            raise UnknownSkillError(skill_name) from exc


def _parse_config_payload(text: str, *, fmt: str) -> dict[str, Any]:
    """Parse raw config text as JSON or YAML into a dictionary payload."""
    if fmt == "json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise FlowConfigLoadError(f"Invalid JSON config: {exc}") from exc
        if not isinstance(payload, dict):
            raise FlowConfigLoadError("Config payload must be a JSON object")
        return payload

    if fmt == "yaml":
        try:
            import yaml
        except Exception as exc:  # pragma: no cover - dependency guard
            raise FlowConfigLoadError("YAML support requires PyYAML installed") from exc
        try:
            payload = yaml.safe_load(text)
        except Exception as exc:
            raise FlowConfigLoadError(f"Invalid YAML config: {exc}") from exc
        if not isinstance(payload, dict):
            raise FlowConfigLoadError("Config payload must be a YAML mapping/object")
        return payload

    raise FlowConfigLoadError(f"Unsupported config format: {fmt}")


def _infer_format(path: Path | None, text: str | None, requested: str) -> str:
    """Infer config format from explicit value, path extension, or payload shape."""
    requested_lower = requested.lower()
    if requested_lower in {"yaml", "json"}:
        return requested_lower
    if requested_lower != "auto":
        raise FlowConfigLoadError(f"Unknown format: {requested}")
    if path is not None:
        if path.suffix.lower() in {".yml", ".yaml"}:
            return "yaml"
        if path.suffix.lower() == ".json":
            return "json"
    content = (text or "").lstrip()
    if content.startswith("{") or content.startswith("["):
        return "json"
    return "yaml"


def load_flow_config(path_or_obj: str | Path | Mapping[str, Any] | FlowConfigV1, *, format: str = "auto") -> FlowConfigV1:
    """Load a `FlowConfigV1` from path, raw text, mapping, or pre-built object."""
    if isinstance(path_or_obj, FlowConfigV1):
        return path_or_obj

    payload: Any
    if isinstance(path_or_obj, Mapping):
        payload = dict(path_or_obj)
    else:
        path: Path | None = None
        text: str | None = None
        if isinstance(path_or_obj, Path):
            path = path_or_obj
            text = path.read_text(encoding="utf-8")
        elif isinstance(path_or_obj, str):
            candidate = Path(path_or_obj)
            if candidate.exists():
                path = candidate
                text = candidate.read_text(encoding="utf-8")
            else:
                text = path_or_obj
        else:
            raise FlowConfigLoadError(f"Unsupported config input type: {type(path_or_obj)!r}")
        # Accept both filesystem paths and inline JSON/YAML text.
        payload_format = _infer_format(path, text, format)
        payload = _parse_config_payload(text or "", fmt=payload_format)

    try:
        return FlowConfigV1.model_validate(payload)
    except ValidationError as exc:
        raise FlowConfigValidationError(str(exc)) from exc


def _validate_transition_targets(config: FlowConfigV1) -> None:
    """Validate that all transition targets reference known steps (or `end`)."""
    seen: set[str] = set()
    for step in config.steps:
        if step.name in seen:
            raise DuplicateStepError(step.name)
        seen.add(step.name)

    if config.entry_step is not None and config.entry_step not in seen:
        raise UnknownEntryStepError(config.entry_step)

    for step in config.steps:
        transition = step.transition
        if transition.kind == "then":
            assert transition.next_step is not None
            if transition.next_step != END_STEP and transition.next_step not in seen:
                raise InvalidTransitionError(
                    step.name,
                    f"next_step '{transition.next_step}' not found",
                )
            continue
        if transition.kind == "branch":
            assert transition.mapping is not None
            for value in transition.mapping.values():
                if value != END_STEP and value not in seen:
                    raise InvalidTransitionError(
                        step.name,
                        f"branch target '{value}' not found",
                    )
            continue
        if transition.kind == "route_to":
            assert transition.allowed is not None
            for value in transition.allowed:
                if value != END_STEP and value not in seen:
                    raise InvalidTransitionError(
                        step.name,
                        f"route_to target '{value}' not found",
                    )


def validate_flow_config(config: FlowConfigV1) -> FlowConfigV1:
    """Run compile-time validation checks and return the same config instance."""
    _validate_transition_targets(config)
    return config


def _transition_to_spec(transition: TransitionConfigV1):
    """Convert transition config model into runtime transition spec object."""
    if transition.kind == "then":
        assert transition.next_step is not None
        return then(transition.next_step)
    if transition.kind == "end":
        return end()
    if transition.kind == "branch":
        assert transition.router is not None
        assert transition.mapping is not None
        return branch(router=transition.router, mapping=transition.mapping)
    assert transition.allowed is not None
    return route_to(allowed=transition.allowed)


def flow_config_to_spec(
    config: FlowConfigV1,
    *,
    tool_resolver: ToolResolver,
    agent_resolver: AgentResolver,
    policy_resolver: PolicyResolver | None = None,
    skill_resolver: SkillResolver | None = None,
) -> GovernedFlowSpec:
    """Compile validated config models into a `GovernedFlowSpec`."""
    validate_flow_config(config)

    # Resolve each executor name to a concrete tool/agent object before runtime.
    steps: list[GovernedStepSpec] = []
    for step_cfg in config.steps:
        tool = None
        agent = None
        if step_cfg.tool is not None:
            tool = tool_resolver.resolve(step_cfg.tool)
        if step_cfg.agent is not None:
            agent = agent_resolver.resolve(step_cfg.agent)
        steps.append(
            GovernedStepSpec(
                name=step_cfg.name,
                tool=tool,
                agent=agent,
                required_artifacts=list(step_cfg.required_artifacts),
                emitted_artifact=step_cfg.emitted_artifact,
                approval_override=step_cfg.approval_override,
                transition=_transition_to_spec(step_cfg.transition),
            )
        )

    # Policies and skills are optional but must resolve at compile time if declared.
    policies: list[Any] = []
    if config.policies:
        if policy_resolver is None:
            raise UnknownPolicyError(config.policies[0])
        for policy_name in config.policies:
            policies.append(policy_resolver.resolve(policy_name))

    skills: list[Any] = []
    if config.skills:
        if skill_resolver is None:
            raise UnknownSkillError(config.skills[0])
        for skill_name in config.skills:
            skills.append(skill_resolver.resolve(skill_name))

    channels = [
        ChannelSpec(name=channel.name, reducer=channel.reducer, initial=channel.initial)
        for channel in config.channels
    ]

    return GovernedFlowSpec(
        name=config.name,
        steps=steps,
        entry_step=config.entry_step,
        policies=policies,
        skills=skills,
        channels=channels,
        interrupts=InterruptContract(
            ttl_seconds=config.interrupts.ttl_seconds,
            max_pending=config.interrupts.max_pending,
        ),
    )


def _coerce_policy_resolver(policy_registry: Mapping[str, Any] | PolicyResolver | None) -> PolicyResolver | None:
    """Normalize policy registry input into a policy resolver implementation."""
    if policy_registry is None:
        return None
    if isinstance(policy_registry, PolicyResolver):
        return policy_registry
    return MappingPolicyResolver(policy_registry)


def _coerce_skill_resolver(skill_registry: SkillRegistry | Mapping[str, Any] | SkillResolver | None) -> SkillResolver | None:
    """Normalize skill registry input into a skill resolver implementation."""
    if skill_registry is None:
        return None
    if isinstance(skill_registry, SkillResolver):
        return skill_registry
    return RegistrySkillResolver(skill_registry)


def governed_flow_from_config(
    config_or_path: str | Path | Mapping[str, Any] | FlowConfigV1,
    *,
    tool_registry: ToolRegistry,
    agent_registry: AgentRegistry,
    policy_registry: Mapping[str, Any] | PolicyResolver | None = None,
    skill_registry: SkillRegistry | Mapping[str, Any] | SkillResolver | None = None,
    runtime_overrides: Mapping[str, Any] | None = None,
    format: str = "auto",
) -> GovernedFlow:
    """Load, compile, and return an executable governed flow from config input."""
    config = load_flow_config(config_or_path, format=format)
    spec = flow_config_to_spec(
        config,
        tool_resolver=RegistryToolResolver(tool_registry),
        agent_resolver=RegistryAgentResolver(agent_registry),
        policy_resolver=_coerce_policy_resolver(policy_registry),
        skill_resolver=_coerce_skill_resolver(skill_registry),
    )
    kwargs = dict(runtime_overrides or {})
    return governed_flow(spec, **kwargs)
