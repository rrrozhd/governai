from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from governai.app.spec import GovernedFlowSpec
from governai.runtime.reducers import ReducerRegistry
from governai.runtime.interrupts import InterruptManager
from governai.runtime.local import LocalRuntime
from governai.runtime.run_store import InMemoryRunStore, RunStore
from governai.workflows.base import Workflow
from governai.workflows.decorators import step


@dataclass
class GovernedFlow:
    """Compiled governed flow wrapper around the core Workflow runtime."""

    spec: GovernedFlowSpec
    workflow: Workflow[Any, Any]

    async def run(self, data: Any):
        """Run."""
        return await self.workflow.run(data)

    async def resume(self, run_id: str, payload: Any):
        """Resume."""
        return await self.workflow.resume(run_id, payload)

    async def resume_from_checkpoint(self, checkpoint_id: str, payload: Any = None):
        """Resume from checkpoint."""
        return await self.workflow.resume_from_checkpoint(checkpoint_id, payload)

    def get_run_state(self, run_id: str):
        """Get run state."""
        return self.workflow.get_run_state(run_id)


def _safe_class_name(name: str) -> str:
    """Internal helper to safe class name."""
    cleaned = re.sub(r"[^0-9a-zA-Z_]", "_", name)
    if not cleaned:
        cleaned = "GovernedFlow"
    if cleaned[0].isdigit():
        cleaned = f"Flow_{cleaned}"
    return cleaned


def _apply_transition(definition: Any, transition: Any) -> Any:
    """Internal helper to apply transition."""
    if transition is None:
        return definition.then_end()

    kind = transition.kind
    if kind == "then":
        if not transition.next_step:
            raise ValueError("then transition requires next_step")
        return definition.then(transition.next_step)
    if kind == "end":
        return definition.then_end()
    if kind == "branch":
        if not transition.router or not transition.mapping:
            raise ValueError("branch transition requires router and mapping")
        return definition.branch(router=transition.router, mapping=transition.mapping)
    if kind == "route_to":
        if not transition.allowed:
            raise ValueError("route_to transition requires allowed list")
        return definition.route_to(allowed=transition.allowed)

    raise ValueError(f"Unsupported transition kind: {kind}")


def governed_flow(
    spec: GovernedFlowSpec,
    *,
    runtime: LocalRuntime | None = None,
    run_store: RunStore | None = None,
    execution_backend: Any = None,
    interrupt_manager: InterruptManager | None = None,
    policy_engine: Any = None,
    approval_engine: Any = None,
    audit_emitter: Any = None,
    tool_registry: Any = None,
    agent_registry: Any = None,
    reducer_registry: ReducerRegistry | None = None,
) -> GovernedFlow:
    """Compile a declarative spec into a governed executable flow."""

    attrs: dict[str, Any] = {}
    for step_spec in spec.steps:
        if (step_spec.tool is None) == (step_spec.agent is None):
            raise ValueError(f"Step {step_spec.name} must define exactly one of tool/agent")
        definition = step(
            step_spec.name,
            tool=step_spec.tool,
            agent=step_spec.agent,
            required_artifacts=list(step_spec.required_artifacts),
            emitted_artifact=step_spec.emitted_artifact,
            approval_override=step_spec.approval_override,
        )
        attrs[step_spec.name] = _apply_transition(definition, step_spec.transition)

    if spec.entry_step is not None:
        attrs["entry_step"] = spec.entry_step

    compiled_cls = type(_safe_class_name(spec.name), (Workflow,), attrs)

    channel_reducers = {channel.name: channel.reducer for channel in spec.channels}
    channel_defaults = {channel.name: channel.initial for channel in spec.channels}

    local_runtime = runtime or LocalRuntime(
        policy_engine=policy_engine,
        approval_engine=approval_engine,
        audit_emitter=audit_emitter,
        run_store=run_store or InMemoryRunStore(),
        execution_backend=execution_backend,
        interrupt_manager=interrupt_manager
        or InterruptManager(default_ttl_seconds=spec.interrupts.ttl_seconds),
        interrupt_max_pending=spec.interrupts.max_pending,
        reducer_registry=reducer_registry,
        channel_reducers=channel_reducers,
        channel_defaults=channel_defaults,
    )

    workflow = compiled_cls(
        runtime=local_runtime,
        tool_registry=tool_registry,
        skills=list(spec.skills),
        policy_engine=policy_engine,
        approval_engine=approval_engine,
        audit_emitter=audit_emitter,
        agent_registry=agent_registry,
        run_store=run_store,
        execution_backend=execution_backend,
        interrupt_manager=interrupt_manager,
    )

    for policy in spec.policies:
        workflow.runtime.policy_engine.register(policy, workflow_name=workflow.name)

    return GovernedFlow(spec=spec, workflow=workflow)
