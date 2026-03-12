from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ValidationError

from governai.agents.base import Agent
from governai.agents.context import AgentExecutionContext
from governai.agents.exceptions import AgentExecutionError
from governai.approvals.engine import ApprovalEngine
from governai.audit.emitter import emit_event
from governai.audit.memory import InMemoryAuditEmitter
from governai.models.approval import ApprovalDecision, ApprovalDecisionType
from governai.models.command import Command
from governai.models.common import DeterminismMode, END_STEP, EventType, RunStatus
from governai.models.policy import PolicyContext
from governai.models.resume import ResumeApproval, ResumeInterrupt, ResumePayload
from governai.models.run_state import RunState
from governai.policies.base import run_policy
from governai.policies.engine import PolicyEngine
from governai.runtime.context import ExecutionContext
from governai.runtime.interrupts import InterruptManager
from governai.runtime.reducers import Reducer, ReducerRegistry
from governai.runtime.run_store import InMemoryRunStore, RunStore
from governai.tools.base import Tool
from governai.workflows.exceptions import (
    ApprovalRejectedError,
    ApprovalRequiredError,
    IllegalTransitionError,
    PolicyDeniedError,
)
from governai.workflows.runner import resolve_next_step
from governai.workflows.transitions import (
    BoundedRoutingTransition,
    RuleBasedTransition,
    StrictTransition,
)
from governai.execution.backends import AsyncBackend, ExecutionBackend


class LocalRuntime:
    def __init__(
        self,
        *,
        policy_engine: PolicyEngine | None = None,
        approval_engine: ApprovalEngine | None = None,
        audit_emitter: InMemoryAuditEmitter | None = None,
        run_store: RunStore | None = None,
        execution_backend: ExecutionBackend | None = None,
        interrupt_manager: InterruptManager | None = None,
        interrupt_max_pending: int = 1,
        reducer_registry: ReducerRegistry | None = None,
        channel_reducers: dict[str, str | Reducer] | None = None,
        channel_defaults: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the local in-process runtime with governance defaults."""
        from governai.agents.registry import AgentRegistry

        self.policy_engine = policy_engine or PolicyEngine()
        self.approval_engine = approval_engine or ApprovalEngine()
        self.audit_emitter = audit_emitter or InMemoryAuditEmitter()
        self.agent_registry = AgentRegistry()
        self.run_store = run_store or InMemoryRunStore()
        self.execution_backend = execution_backend or AsyncBackend()
        self.interrupt_manager = interrupt_manager or InterruptManager()
        self.interrupt_max_pending = max(0, int(interrupt_max_pending))
        self.reducer_registry = reducer_registry or ReducerRegistry()
        self.channel_reducers = dict(channel_reducers or {})
        self.channel_defaults = dict(channel_defaults or {})
        self._runs: dict[str, RunState] = {}

    def get_run_state(self, run_id: str) -> RunState:
        """Return in-memory run state for a known run id."""
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise KeyError(f"Unknown run_id: {run_id}") from exc

    async def aget_run_state(self, run_id: str) -> RunState:
        """Return run state, loading it from the configured store when needed."""
        return await self._load_state(run_id)

    async def run_workflow(self, workflow: Any, data: Any) -> RunState:
        """Start a new workflow run and advance until blocked or completed."""
        # Every run starts with a fresh epoch for interrupt race protection.
        run_id = str(uuid.uuid4())
        epoch = self.interrupt_manager.bump_epoch(run_id)
        state = RunState(
            run_id=run_id,
            thread_id=run_id,
            epoch=epoch,
            workflow_name=workflow.name,
            status=RunStatus.PENDING,
            current_step=workflow.entry_step_name,
            channels=deepcopy(self.channel_defaults),
        )
        self._runs[run_id] = state
        await self._persist_state(state)
        payload = self._to_payload(data)

        await emit_event(
            self.audit_emitter,
            run_id=run_id,
            workflow_name=workflow.name,
            event_type=EventType.RUN_STARTED,
            payload={"entry_step": workflow.entry_step_name},
        )

        state.status = RunStatus.RUNNING
        state.touch()
        await self._persist_state(state)
        return await self._advance(workflow, state, payload)

    async def resume_workflow(self, workflow: Any, run_id: str, payload: Any) -> RunState:
        """Resume a run that is waiting on approval or interrupt input."""
        state = await self._load_state(run_id)
        normalized = self._normalize_resume_payload(payload)
        if state.status == RunStatus.WAITING_APPROVAL:
            return await self._resume_approval(workflow, state, normalized)
        if state.status == RunStatus.WAITING_INTERRUPT:
            return await self._resume_interrupt(workflow, state, normalized)
        raise ApprovalRequiredError(
            f"Run {run_id} is not resumable (status={state.status.value})"
        )

    async def resume_from_checkpoint(
        self, workflow: Any, checkpoint_id: str, payload: Any = None
    ) -> RunState:
        """Restore a checkpoint snapshot into a new run and continue execution."""
        snapshot = await self.run_store.get_checkpoint(checkpoint_id)
        if snapshot is None:
            raise KeyError(f"Unknown checkpoint_id: {checkpoint_id}")

        run_id = str(uuid.uuid4())
        restored = snapshot.model_copy(deep=True)
        restored.run_id = run_id
        restored.pending_approval = None
        restored.pending_interrupt_id = None
        restored.error = None
        restored.status = RunStatus.RUNNING
        restored.metadata.pop("pending_input", None)
        restored.metadata.pop("pending_interrupt_resume", None)
        restored.epoch = self.interrupt_manager.bump_epoch(run_id)
        restored.touch()
        await self._persist_state(restored)

        await emit_event(
            self.audit_emitter,
            run_id=restored.run_id,
            workflow_name=restored.workflow_name,
            event_type=EventType.CHECKPOINT_RESTORED,
            payload={
                "source_checkpoint_id": checkpoint_id,
                "thread_id": restored.thread_id,
            },
        )
        await emit_event(
            self.audit_emitter,
            run_id=restored.run_id,
            workflow_name=restored.workflow_name,
            event_type=EventType.RUN_STARTED,
            payload={
                "entry_step": restored.current_step,
                "resumed_from_checkpoint": checkpoint_id,
            },
        )
        payload_value = payload
        if payload_value is None:
            payload_value = restored.metadata.pop("pending_input", None)
        return await self._advance(workflow, restored, payload_value)

    async def _resume_approval(
        self, workflow: Any, state: RunState, payload: ResumePayload
    ) -> RunState:
        """Apply approval decision and continue or fail the waiting run."""
        if state.pending_approval is None:
            raise ApprovalRequiredError(f"Run {state.run_id} is not waiting for approval")
        if not isinstance(payload, ResumeApproval):
            raise ApprovalRequiredError("Approval resume requires ResumeApproval payload")

        normalized = self.approval_engine.normalize_decision(payload.decision)
        if normalized.decision == ApprovalDecisionType.REJECT:
            await emit_event(
                self.audit_emitter,
                run_id=state.run_id,
                workflow_name=state.workflow_name,
                step_name=state.current_step,
                event_type=EventType.APPROVAL_REJECTED,
                payload={"reason": normalized.reason or "rejected"},
            )
            state.status = RunStatus.FAILED
            state.error = normalized.reason or "approval rejected"
            state.pending_approval = None
            state.touch()
            await self._persist_state(state)
            await emit_event(
                self.audit_emitter,
                run_id=state.run_id,
                workflow_name=state.workflow_name,
                event_type=EventType.RUN_FAILED,
                payload={"error": state.error},
            )
            raise ApprovalRejectedError(state.error)

        step_name = state.pending_approval.step_name
        approved_steps = self._approved_steps(state)
        approved_steps.add(step_name)
        state.metadata["approved_steps"] = sorted(approved_steps)
        pending_payload = state.metadata.pop("pending_input", None)

        await emit_event(
            self.audit_emitter,
            run_id=state.run_id,
            workflow_name=state.workflow_name,
            step_name=state.current_step,
            event_type=EventType.APPROVAL_GRANTED,
            payload={"decided_by": normalized.decided_by, "reason": normalized.reason},
        )

        state.pending_approval = None
        state.status = RunStatus.RUNNING
        state.touch()
        await self._persist_state(state)
        return await self._advance(workflow, state, pending_payload)

    async def _resume_interrupt(
        self, workflow: Any, state: RunState, payload: ResumePayload
    ) -> RunState:
        """Resolve pending interrupt input and continue workflow execution."""
        if state.pending_interrupt_id is None:
            raise ApprovalRequiredError(f"Run {state.run_id} is not waiting for interrupt input")
        if not isinstance(payload, ResumeInterrupt):
            raise ApprovalRequiredError("Interrupt resume requires ResumeInterrupt payload")

        try:
            resolution = self.interrupt_manager.resolve(
                run_id=state.run_id,
                interrupt_id=payload.interrupt_id,
                response=payload.response,
                epoch=payload.epoch if payload.epoch is not None else state.epoch,
            )
        except ValueError as exc:
            message = str(exc)
            event = EventType.INTERRUPT_EXPIRED if "expired" in message else EventType.INTERRUPT_REJECTED_EPOCH
            await emit_event(
                self.audit_emitter,
                run_id=state.run_id,
                workflow_name=state.workflow_name,
                step_name=state.current_step,
                event_type=event,
                payload={"interrupt_id": payload.interrupt_id, "error": message},
            )
            raise

        state.pending_interrupt_id = None
        state.status = RunStatus.RUNNING
        state.epoch = self.interrupt_manager.bump_epoch(state.run_id)
        state.touch()
        await self._persist_state(state)
        await emit_event(
            self.audit_emitter,
            run_id=state.run_id,
            workflow_name=state.workflow_name,
            step_name=state.current_step,
            event_type=EventType.INTERRUPT_RESOLVED,
            payload={"interrupt_id": payload.interrupt_id, "response": self._to_payload(resolution.response)},
        )

        pending = state.metadata.pop("pending_interrupt_resume", None) or {}
        step_name = pending.get("step_name")
        output_payload = pending.get("output_payload", {})
        handoff_agent = pending.get("handoff_agent")
        command_payload = pending.get("command")
        command = None
        if isinstance(command_payload, dict):
            command = Command.model_validate(command_payload)
        if not step_name:
            # If no pending transition context was stored, continue with raw response.
            return await self._advance(workflow, state, resolution.response)

        step = workflow.get_step(step_name)
        next_step = self._resolve_next_step_for_step(
            workflow=workflow,
            step=step,
            output_payload=output_payload,
            handoff_agent=handoff_agent,
            command=command,
        )
        await self._emit_transition_events(
            state=state,
            step_name=step_name,
            next_step=next_step,
            handoff_agent=handoff_agent,
        )
        if next_step == END_STEP:
            state.current_step = None
            state.status = RunStatus.COMPLETED
            state.touch()
            await self._persist_state(state)
            await emit_event(
                self.audit_emitter,
                run_id=state.run_id,
                workflow_name=state.workflow_name,
                event_type=EventType.RUN_COMPLETED,
                payload={"completed_steps": list(state.completed_steps)},
            )
            return state

        state.current_step = next_step
        state.touch()
        await self._persist_state(state)
        next_payload = resolution.response if resolution.response is not None else output_payload
        return await self._advance(workflow, state, next_payload)

    async def _advance(self, workflow: Any, state: RunState, payload: Any) -> RunState:
        """Run the main deterministic execution loop until status changes."""
        while state.status == RunStatus.RUNNING:
            step_name = state.current_step
            if step_name is None:
                state.status = RunStatus.COMPLETED
                state.touch()
                await self._persist_state(state)
                await emit_event(
                    self.audit_emitter,
                    run_id=state.run_id,
                    workflow_name=state.workflow_name,
                    event_type=EventType.RUN_COMPLETED,
                    payload={"completed_steps": list(state.completed_steps)},
                )
                return state

            step = workflow.get_step(step_name)
            await emit_event(
                self.audit_emitter,
                run_id=state.run_id,
                workflow_name=state.workflow_name,
                step_name=step.name,
                event_type=EventType.STEP_ENTERED,
            )

            for required in step.required_artifacts:
                if required not in state.artifacts:
                    raise KeyError(f"Step {step.name} requires missing artifact '{required}'")

            executable = step.executor
            # Approval gates short-circuit execution and persist pending input for resume.
            if self._requires_approval(step, executable, state):
                request = self.approval_engine.create_request(
                    run_id=state.run_id,
                    workflow_name=state.workflow_name,
                    step_name=step.name,
                    executor_name=executable.name,
                    reason=f"Approval required for {executable.name}",
                )
                state.pending_approval = request
                state.status = RunStatus.WAITING_APPROVAL
                state.metadata["pending_input"] = self._to_payload(payload)
                state.touch()
                await self._persist_state(state)
                await emit_event(
                    self.audit_emitter,
                    run_id=state.run_id,
                    workflow_name=state.workflow_name,
                    step_name=step.name,
                    event_type=EventType.APPROVAL_REQUESTED,
                    payload=request.model_dump(mode="json"),
                )
                return state

            policy_ctx = PolicyContext(
                workflow_name=workflow.name,
                step_name=step.name,
                tool_name=executable.name,
                capabilities=list(getattr(executable, "capabilities", [])),
                side_effect=bool(getattr(executable, "side_effect", False)),
                artifacts=state.artifacts,
                pending_approval=state.pending_approval is not None,
                metadata=dict(state.metadata),
            )
            try:
                await self._evaluate_policies(state, workflow, step.name, policy_ctx)
            except Exception as exc:
                state.status = RunStatus.FAILED
                state.error = str(exc)
                state.touch()
                await self._persist_state(state)
                await emit_event(
                    self.audit_emitter,
                    run_id=state.run_id,
                    workflow_name=state.workflow_name,
                    step_name=step.name,
                    event_type=EventType.RUN_FAILED,
                    payload={"error": str(exc)},
                )
                raise

            try:
                # Exactly one executor type is allowed per step definition.
                if step.tool is not None:
                    output_payload, command = await self._execute_tool(
                        state=state,
                        workflow=workflow,
                        step_name=step.name,
                        tool=step.tool,
                        payload=payload,
                    )
                    handoff_agent = None
                else:
                    output_payload, handoff_agent, command = await self._execute_agent(
                        state=state,
                        workflow=workflow,
                        step_name=step.name,
                        agent=step.agent,
                        payload=payload,
                    )
            except ApprovalRequiredError as exc:
                request = self.approval_engine.create_request(
                    run_id=state.run_id,
                    workflow_name=state.workflow_name,
                    step_name=step.name,
                    executor_name=executable.name,
                    reason=str(exc),
                )
                state.pending_approval = request
                state.status = RunStatus.WAITING_APPROVAL
                state.metadata["pending_input"] = self._to_payload(payload)
                state.touch()
                await self._persist_state(state)
                await emit_event(
                    self.audit_emitter,
                    run_id=state.run_id,
                    workflow_name=state.workflow_name,
                    step_name=step.name,
                    event_type=EventType.APPROVAL_REQUESTED,
                    payload=request.model_dump(mode="json"),
                )
                return state
            except Exception as exc:
                state.status = RunStatus.FAILED
                state.error = str(exc)
                state.touch()
                await self._persist_state(state)
                await emit_event(
                    self.audit_emitter,
                    run_id=state.run_id,
                    workflow_name=state.workflow_name,
                    step_name=step.name,
                    event_type=EventType.RUN_FAILED,
                    payload={"error": str(exc)},
                )
                raise

            state_output = output_payload
            if command is not None:
                # Commands can atomically mutate channel state and override step output.
                self._apply_state_update(state, command.state_update)
                if command.output is not None:
                    state_output = self._to_payload(command.output)

            artifact_key = step.emitted_artifact or step.name
            state.artifacts[artifact_key] = state_output
            if step.name not in state.completed_steps:
                state.completed_steps.append(step.name)
            state.touch()
            await self._persist_state(state)

            approved_steps = self._approved_steps(state)
            if step.name in approved_steps:
                approved_steps.remove(step.name)
                state.metadata["approved_steps"] = sorted(approved_steps)

            if command is not None and command.interrupt is not None:
                # Command interrupts are runtime-level user questions (non-approval).
                request = self.interrupt_manager.create(
                    run_id=state.run_id,
                    step_name=step.name,
                    message=command.interrupt.message,
                    context=dict(command.interrupt.context),
                    ttl_seconds=command.interrupt.ttl_seconds,
                    epoch=state.epoch,
                    max_pending=self.interrupt_max_pending,
                )
                state.pending_interrupt_id = request.interrupt_id
                state.status = RunStatus.WAITING_INTERRUPT
                state.metadata["pending_interrupt_resume"] = {
                    "step_name": step.name,
                    "output_payload": self._to_payload(state_output),
                    "handoff_agent": handoff_agent,
                    "command": command.model_dump(mode="json"),
                }
                state.touch()
                await self._persist_state(state)
                await emit_event(
                    self.audit_emitter,
                    run_id=state.run_id,
                    workflow_name=state.workflow_name,
                    step_name=step.name,
                    event_type=EventType.INTERRUPT_REQUESTED,
                    payload={
                        "interrupt_id": request.interrupt_id,
                        "message": request.message,
                        "context": request.context,
                        "epoch": request.epoch,
                        "expires_at": request.expires_at,
                    },
                )
                return state

            try:
                next_step = self._resolve_next_step_for_step(
                    workflow=workflow,
                    step=step,
                    output_payload=state_output,
                    handoff_agent=handoff_agent,
                    command=command,
                )
            except Exception as exc:
                if handoff_agent is not None:
                    await emit_event(
                        self.audit_emitter,
                        run_id=state.run_id,
                        workflow_name=state.workflow_name,
                        step_name=step.name,
                        event_type=EventType.AGENT_HANDOFF_REJECTED,
                        payload={"next_agent": handoff_agent},
                    )
                state.status = RunStatus.FAILED
                state.error = str(exc)
                state.touch()
                await self._persist_state(state)
                await emit_event(
                    self.audit_emitter,
                    run_id=state.run_id,
                    workflow_name=state.workflow_name,
                    step_name=step.name,
                    event_type=EventType.RUN_FAILED,
                    payload={"error": str(exc)},
                )
                raise

            await self._emit_transition_events(
                state=state,
                step_name=step.name,
                next_step=next_step,
                handoff_agent=handoff_agent,
            )

            if next_step == END_STEP:
                state.current_step = None
                state.status = RunStatus.COMPLETED
                state.touch()
                await self._persist_state(state)
                await emit_event(
                    self.audit_emitter,
                    run_id=state.run_id,
                    workflow_name=state.workflow_name,
                    event_type=EventType.RUN_COMPLETED,
                    payload={"completed_steps": list(state.completed_steps)},
                )
                return state

            state.current_step = next_step
            payload = state_output
            await self._persist_state(state)

        return state

    async def execute_named_tool(
        self,
        *,
        state: RunState,
        workflow: Any,
        step_name: str,
        tool_name: str,
        payload: Any,
    ) -> dict[str, Any]:
        """Execute a tool by name for agent nested tool calls."""
        tool = workflow.tool_registry.get(tool_name)
        policy_ctx = PolicyContext(
            workflow_name=workflow.name,
            step_name=step_name,
            tool_name=tool.name,
            capabilities=list(getattr(tool, "capabilities", [])),
            side_effect=bool(getattr(tool, "side_effect", False)),
            artifacts=state.artifacts,
            pending_approval=state.pending_approval is not None,
            metadata={**dict(state.metadata), "nested": True},
        )
        await self._evaluate_policies(state, workflow, step_name, policy_ctx)
        if tool.requires_approval:
            raise ApprovalRequiredError(f"Approval required for nested tool call {tool.name}")
        output_payload, command = await self._execute_tool(
            state=state,
            workflow=workflow,
            step_name=step_name,
            tool=tool,
            payload=payload,
            event_prefix="agent_tool",
        )
        if command is not None:
            raise AgentExecutionError(f"Nested tool call {tool.name} cannot return runtime command")
        return output_payload

    async def _evaluate_policies(
        self,
        state: RunState,
        workflow: Any,
        step_name: str,
        ctx: PolicyContext,
    ) -> None:
        """Run all policies for a workflow and raise on first deny decision."""
        for policy_name, policy_func in self.policy_engine.policies_for(workflow.name):
            decision = await run_policy(policy_func, ctx)
            await emit_event(
                self.audit_emitter,
                run_id=state.run_id,
                workflow_name=state.workflow_name,
                step_name=step_name,
                event_type=EventType.POLICY_CHECKED,
                payload={
                    "policy": policy_name,
                    "allow": decision.allow,
                    "reason": decision.reason,
                    "requires_approval": decision.requires_approval,
                },
            )
            if not decision.allow:
                await emit_event(
                    self.audit_emitter,
                    run_id=state.run_id,
                    workflow_name=state.workflow_name,
                    step_name=step_name,
                    event_type=EventType.POLICY_DENIED,
                    payload={"policy": policy_name, "reason": decision.reason},
                )
                raise PolicyDeniedError(decision.reason or f"Policy denied: {policy_name}")

    async def _execute_tool(
        self,
        *,
        state: RunState,
        workflow: Any,
        step_name: str,
        tool: Tool,
        payload: Any,
        event_prefix: str = "tool",
    ) -> tuple[dict[str, Any], Command | None]:
        """Execute one tool and normalize optional runtime command envelopes."""
        event_started = EventType.TOOL_EXECUTION_STARTED
        event_completed = EventType.TOOL_EXECUTION_COMPLETED
        event_failed = EventType.TOOL_EXECUTION_FAILED
        if event_prefix == "agent_tool":
            event_started = EventType.AGENT_TOOL_CALL_STARTED
            event_completed = EventType.AGENT_TOOL_CALL_COMPLETED
            event_failed = EventType.AGENT_TOOL_CALL_FAILED

        await emit_event(
            self.audit_emitter,
            run_id=state.run_id,
            workflow_name=state.workflow_name,
            step_name=step_name,
            event_type=event_started,
            payload={"tool_name": tool.name},
        )

        context = ExecutionContext(
            run_id=state.run_id,
            workflow_name=state.workflow_name,
            step_name=step_name,
            artifacts=state.artifacts,
            channels=state.channels,
            metadata=state.metadata,
            approval_request=state.pending_approval,
        )

        try:
            output = await self.execution_backend.call(tool.execute, context, payload)
        except Exception:
            await emit_event(
                self.audit_emitter,
                run_id=state.run_id,
                workflow_name=state.workflow_name,
                step_name=step_name,
                event_type=event_failed,
                payload={"tool_name": tool.name},
            )
            raise

        payload_out, command = self._extract_command(output)
        await emit_event(
            self.audit_emitter,
            run_id=state.run_id,
            workflow_name=state.workflow_name,
            step_name=step_name,
            event_type=event_completed,
            payload={"tool_name": tool.name},
        )
        return payload_out, command

    async def _execute_agent(
        self,
        *,
        state: RunState,
        workflow: Any,
        step_name: str,
        agent: Agent,
        payload: Any,
    ) -> tuple[dict[str, Any], str | None, Command | None]:
        """Execute one agent step, including optional handoff validation."""
        await emit_event(
            self.audit_emitter,
            run_id=state.run_id,
            workflow_name=state.workflow_name,
            step_name=step_name,
            event_type=EventType.AGENT_ENTERED,
            payload={"agent_name": agent.name},
        )

        base_context = ExecutionContext(
            run_id=state.run_id,
            workflow_name=state.workflow_name,
            step_name=step_name,
            artifacts=state.artifacts,
            channels=state.channels,
            metadata=state.metadata,
            approval_request=state.pending_approval,
        )

        async def tool_caller(tool_name: str, tool_payload: Any) -> dict[str, Any]:
            """Delegate nested agent tool calls back through runtime guardrails."""
            return await self.execute_named_tool(
                state=state,
                workflow=workflow,
                step_name=step_name,
                tool_name=tool_name,
                payload=tool_payload,
            )

        agent_context = AgentExecutionContext(
            base_context=base_context,
            allowed_tools=agent.allowed_tools,
            max_tool_calls=agent.max_tool_calls,
            tool_caller=tool_caller,
        )

        try:
            result = await agent.execute(agent_context, payload)
        except Exception:
            await emit_event(
                self.audit_emitter,
                run_id=state.run_id,
                workflow_name=state.workflow_name,
                step_name=step_name,
                event_type=EventType.AGENT_FAILED,
                payload={"agent_name": agent.name},
            )
            raise

        if result.status == "needs_approval":
            raise ApprovalRequiredError(result.reason or f"Agent {agent.name} requested approval")
        if result.status == "failed":
            raise AgentExecutionError(result.reason or f"Agent {agent.name} failed")

        output_payload, command = self._extract_command(result.output_payload or {})
        handoff_target = None
        if result.status == "handoff":
            handoff_target = result.next_agent
            await emit_event(
                self.audit_emitter,
                run_id=state.run_id,
                workflow_name=state.workflow_name,
                step_name=step_name,
                event_type=EventType.AGENT_HANDOFF_PROPOSED,
                payload={"agent_name": agent.name, "next_agent": handoff_target},
            )
            if handoff_target and not workflow.agent_registry.has(handoff_target):
                await emit_event(
                    self.audit_emitter,
                    run_id=state.run_id,
                    workflow_name=state.workflow_name,
                    step_name=step_name,
                    event_type=EventType.AGENT_HANDOFF_REJECTED,
                    payload={"next_agent": handoff_target, "reason": "unknown agent"},
                )
                raise AgentExecutionError(f"Unknown handoff target agent: {handoff_target}")

        await emit_event(
            self.audit_emitter,
            run_id=state.run_id,
            workflow_name=state.workflow_name,
            step_name=step_name,
            event_type=EventType.AGENT_COMPLETED,
            payload={"agent_name": agent.name, "status": result.status},
        )
        return output_payload, handoff_target, command

    async def _emit_transition_events(
        self,
        *,
        state: RunState,
        step_name: str,
        next_step: str,
        handoff_agent: str | None,
    ) -> None:
        """Emit transition audit events after next-step resolution."""
        if handoff_agent is not None:
            await emit_event(
                self.audit_emitter,
                run_id=state.run_id,
                workflow_name=state.workflow_name,
                step_name=step_name,
                event_type=EventType.AGENT_HANDOFF_ACCEPTED,
                payload={"next_agent": handoff_agent, "next_step": next_step},
            )

        await emit_event(
            self.audit_emitter,
            run_id=state.run_id,
            workflow_name=state.workflow_name,
            step_name=step_name,
            event_type=EventType.TRANSITION_CHOSEN,
            payload={"next_step": next_step},
        )

    def _resolve_next_step_for_step(
        self,
        *,
        workflow: Any,
        step: Any,
        output_payload: dict[str, Any],
        handoff_agent: str | None,
        command: Command | None,
    ) -> str:
        """Resolve next step using command override or declared transition rules."""
        if command is not None and command.goto is not None:
            return self._validate_goto(
                workflow=workflow,
                step=step,
                proposed_next=command.goto,
                handoff_agent=handoff_agent,
            )
        return resolve_next_step(
            step=step,
            output_payload=output_payload,
            steps=workflow.steps,
            handoff_agent=handoff_agent,
        )

    def _validate_goto(
        self, *, workflow: Any, step: Any, proposed_next: str, handoff_agent: str | None
    ) -> str:
        """Validate command-driven goto against deterministic transition constraints."""
        next_step = END_STEP if proposed_next.lower() == "end" else proposed_next
        transition = step.transition
        mode = step.determinism_mode
        if transition is None or mode is None:
            raise IllegalTransitionError(f"Step {step.name} has no transition configured")

        allowed: set[str]
        if mode == DeterminismMode.STRICT:
            assert isinstance(transition, StrictTransition)
            allowed = {transition.next_step}
        elif mode == DeterminismMode.RULE_BASED:
            assert isinstance(transition, RuleBasedTransition)
            allowed = set(transition.mapping.values())
        else:
            assert isinstance(transition, BoundedRoutingTransition)
            allowed = set(transition.allowed)

        if next_step not in allowed:
            raise IllegalTransitionError(
                f"Step {step.name} command goto '{next_step}' violates determinism constraints"
            )
        if next_step != END_STEP and next_step not in workflow.steps:
            raise IllegalTransitionError(f"Step {step.name} goto resolved unknown step {next_step}")
        if handoff_agent is not None:
            if next_step == END_STEP:
                raise IllegalTransitionError(
                    f"Agent step {step.name} proposed handoff to {handoff_agent} but transition ended"
                )
            candidate = workflow.steps[next_step]
            if candidate.agent is None or candidate.agent.name != handoff_agent:
                raise IllegalTransitionError(
                    f"Agent handoff target {handoff_agent} does not match workflow next step {next_step}"
                )
        return next_step

    def _apply_state_update(self, state: RunState, update: dict[str, Any]) -> None:
        """Apply reducer-based channel state updates from a runtime command."""
        if not update:
            return
        for channel_name, value in update.items():
            reducer = self._channel_reducer(channel_name)
            current = state.channels.get(channel_name)
            state.channels[channel_name] = reducer(current, value)

    def _channel_reducer(self, channel_name: str) -> Reducer:
        """Resolve configured reducer for a channel name."""
        reducer_value = self.channel_reducers.get(channel_name, "replace")
        if callable(reducer_value):
            return reducer_value
        return self.reducer_registry.resolve(str(reducer_value))

    def _extract_command(self, output: Any) -> tuple[dict[str, Any], Command | None]:
        """Extract normalized payload plus optional runtime command from step output."""
        if output is None:
            return {}, None
        if isinstance(output, Command):
            payload = output.output
            if payload is None:
                payload = {}
            return self._to_payload(payload), output
        if isinstance(output, dict) and output.get("__command__") is True:
            command = Command.model_validate(output.get("command", {}))
            payload = output.get("output", command.output)
            if payload is None:
                payload = {}
            return self._to_payload(payload), command
        return self._to_payload(output), None

    def _normalize_resume_payload(self, payload: Any) -> ResumePayload:
        """Coerce resume payload into `ResumeApproval` or `ResumeInterrupt`."""
        if isinstance(payload, (ResumeApproval, ResumeInterrupt)):
            return payload
        if isinstance(payload, ApprovalDecision) or isinstance(payload, str):
            return ResumeApproval(decision=payload)
        if isinstance(payload, dict):
            if "interrupt_id" in payload:
                return ResumeInterrupt.model_validate(payload)
            if "decision" in payload:
                return ResumeApproval.model_validate(payload)
        try:
            return ResumeApproval.model_validate(payload)
        except ValidationError:
            pass
        try:
            return ResumeInterrupt.model_validate(payload)
        except ValidationError as exc:
            raise TypeError(f"Unsupported resume payload type: {type(payload)!r}") from exc

    def _requires_approval(self, step: Any, executable: Any, state: RunState) -> bool:
        """Return whether the current step must pause for approval before execution."""
        approved_steps = self._approved_steps(state)
        if step.name in approved_steps:
            return False
        if step.approval_override is not None:
            return bool(step.approval_override)
        return bool(getattr(executable, "requires_approval", False))

    @staticmethod
    def _to_payload(data: Any) -> Any:
        """Convert Pydantic objects to JSON-compatible payload dictionaries."""
        if isinstance(data, BaseModel):
            return data.model_dump(mode="json")
        return data

    @staticmethod
    def _approved_steps(state: RunState) -> set[str]:
        """Return steps explicitly approved for the current run state."""
        return set(state.metadata.get("approved_steps", []))

    async def _load_state(self, run_id: str) -> RunState:
        """Load run state from cache or backing run store."""
        state = self._runs.get(run_id)
        if state is not None:
            return state
        loaded = await self.run_store.get(run_id)
        if loaded is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        self._runs[run_id] = loaded
        return loaded

    async def _persist_state(self, state: RunState) -> None:
        """Persist run state and emit checkpoint-written audit event."""
        # The run store owns checkpoint assignment; we preserve parent linkage here.
        previous_checkpoint = state.checkpoint_id
        state.parent_checkpoint_id = previous_checkpoint
        state.checkpoint_id = None
        self._runs[state.run_id] = state
        await self.run_store.put(state)
        await emit_event(
            self.audit_emitter,
            run_id=state.run_id,
            workflow_name=state.workflow_name,
            step_name=state.current_step,
            event_type=EventType.CHECKPOINT_WRITTEN,
            payload={
                "checkpoint_id": state.checkpoint_id,
                "parent_checkpoint_id": state.parent_checkpoint_id,
                "thread_id": state.thread_id,
            },
        )
