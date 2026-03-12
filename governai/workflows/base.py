from __future__ import annotations

from collections import OrderedDict
from typing import Any, Generic, TypeVar

from governai.models.approval import ApprovalDecision
from governai.models.resume import ResumePayload
from governai.models.common import END_STEP
from governai.models.run_state import RunState
from governai.skills.base import Skill
from governai.tools.registry import ToolRegistry
from governai.workflows.exceptions import StepNotFoundError, WorkflowDefinitionError
from governai.workflows.step import StepDefinition
from governai.workflows.transitions import (
    BoundedRoutingTransition,
    RuleBasedTransition,
    StrictTransition,
)

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class WorkflowMeta(type):
    def __new__(mcls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]):
        """Create a new instance of WorkflowMeta."""
        cls = super().__new__(mcls, name, bases, namespace)
        inherited_steps: OrderedDict[str, StepDefinition] = OrderedDict()
        for base in bases:
            inherited = getattr(base, "__steps__", None)
            if inherited:
                inherited_steps.update({k: v.copy() for k, v in inherited.items()})

        declared_steps: OrderedDict[str, StepDefinition] = OrderedDict()
        for attr_name, value in namespace.items():
            if isinstance(value, StepDefinition):
                declared_steps[value.name] = value.copy()

        if not declared_steps and not inherited_steps:
            cls.__steps__ = OrderedDict()
            cls.__entry_step_name__ = None
            return cls

        steps = OrderedDict()
        steps.update(inherited_steps)
        for step_name, step_def in declared_steps.items():
            if step_name in steps:
                raise WorkflowDefinitionError(f"Duplicate step name: {step_name}")
            steps[step_name] = step_def

        for step_name, step_def in steps.items():
            if step_def.transition is None:
                raise WorkflowDefinitionError(f"Step {step_name} missing transition configuration")
            if step_def.determinism_mode is None:
                raise WorkflowDefinitionError(f"Step {step_name} missing determinism mode")

        step_names = set(steps.keys())
        for step_name, step_def in steps.items():
            transition = step_def.transition
            if isinstance(transition, StrictTransition):
                if transition.next_step != END_STEP and transition.next_step not in step_names:
                    raise WorkflowDefinitionError(
                        f"Step {step_name} references unknown next step {transition.next_step}"
                    )
            elif isinstance(transition, RuleBasedTransition):
                for mapped in transition.mapping.values():
                    if mapped != END_STEP and mapped not in step_names:
                        raise WorkflowDefinitionError(
                            f"Step {step_name} branch maps to unknown step {mapped}"
                        )
            elif isinstance(transition, BoundedRoutingTransition):
                for allowed in transition.allowed:
                    if allowed != END_STEP and allowed not in step_names:
                        raise WorkflowDefinitionError(
                            f"Step {step_name} routing allows unknown step {allowed}"
                        )

        entry_step_name = namespace.get("entry_step", None)
        if entry_step_name is None:
            entry_step_name = next(iter(steps))
        if entry_step_name not in steps:
            raise WorkflowDefinitionError(f"Entry step {entry_step_name} not found")

        cls.__steps__ = steps
        cls.__entry_step_name__ = entry_step_name
        return cls


class Workflow(Generic[InputT, OutputT], metaclass=WorkflowMeta):
    entry_step: str | None = None

    def __init__(
        self,
        *,
        runtime: Any = None,
        tool_registry: ToolRegistry | None = None,
        skills: list[Skill] | None = None,
        policy_engine: Any = None,
        approval_engine: Any = None,
        audit_emitter: Any = None,
        agent_registry: Any = None,
        run_store: Any = None,
        execution_backend: Any = None,
        interrupt_manager: Any = None,
        interrupt_max_pending: int = 1,
        reducer_registry: Any = None,
        channel_reducers: dict[str, Any] | None = None,
        channel_defaults: dict[str, Any] | None = None,
    ) -> None:
        """Initialize Workflow."""
        from governai.runtime.local import LocalRuntime

        self.tool_registry = tool_registry or ToolRegistry()
        self.agent_registry = agent_registry
        self._register_step_executors()
        if skills:
            for skill in skills:
                for tool in skill.list_tools():
                    if not self.tool_registry.has(tool.name):
                        self.tool_registry.register(tool)
        self.runtime = runtime or LocalRuntime(
            policy_engine=policy_engine,
            approval_engine=approval_engine,
            audit_emitter=audit_emitter,
            run_store=run_store,
            execution_backend=execution_backend,
            interrupt_manager=interrupt_manager,
            interrupt_max_pending=interrupt_max_pending,
            reducer_registry=reducer_registry,
            channel_reducers=channel_reducers,
            channel_defaults=channel_defaults,
        )
        if self.agent_registry is None:
            self.agent_registry = self.runtime.agent_registry
        else:
            self.runtime.agent_registry = self.agent_registry

    @property
    def name(self) -> str:
        """Name."""
        return self.__class__.__name__

    @property
    def steps(self) -> dict[str, StepDefinition]:
        """Steps."""
        return dict(self.__class__.__steps__)

    @property
    def entry_step_name(self) -> str:
        """Entry step name."""
        entry = self.__class__.__entry_step_name__
        if entry is None:
            raise WorkflowDefinitionError("Workflow has no entry step")
        return entry

    def get_step(self, name: str) -> StepDefinition:
        """Get step."""
        step_def = self.__class__.__steps__.get(name)
        if step_def is None:
            raise StepNotFoundError(f"Step not found: {name}")
        return step_def

    async def run(self, data: InputT) -> RunState:
        """Run."""
        return await self.runtime.run_workflow(self, data)

    async def resume(
        self, run_id: str, payload: ResumePayload | ApprovalDecision | str | dict[str, Any]
    ) -> RunState:
        """Resume."""
        return await self.runtime.resume_workflow(self, run_id, payload)

    async def resume_from_checkpoint(self, checkpoint_id: str, payload: Any = None) -> RunState:
        """Resume from checkpoint."""
        return await self.runtime.resume_from_checkpoint(self, checkpoint_id, payload)

    def get_run_state(self, run_id: str) -> RunState:
        """Get run state."""
        return self.runtime.get_run_state(run_id)

    async def aget_run_state(self, run_id: str) -> RunState:
        """Aget run state."""
        getter = getattr(self.runtime, "aget_run_state", None)
        if getter is None:
            return self.get_run_state(run_id)
        return await getter(run_id)

    def _register_step_executors(self) -> None:
        """Internal helper to register step executors."""
        from governai.agents.registry import AgentRegistry

        if self.agent_registry is None:
            self.agent_registry = AgentRegistry()

        for step_def in self.__class__.__steps__.values():
            if step_def.tool is not None and not self.tool_registry.has(step_def.tool.name):
                self.tool_registry.register(step_def.tool)
            if step_def.agent is not None and not self.agent_registry.has(step_def.agent.name):
                self.agent_registry.register(step_def.agent)
