from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from typing import Any

from pydantic import ValidationError

from governai.agents.exceptions import AgentExecutionError, AgentLimitExceededError, AgentToolNotAllowedError
from governai.agents.result import AgentResult, AgentTask
from governai.extensions.remote import (
    RemoteAgentExecutionRequest,
    RemoteAgentExecutionResponse,
    RemoteExecutionFailure,
    RemoteToolCallRequest,
    RemoteToolExecutionRequest,
    RemoteToolExecutionResponse,
)
from governai.runtime.context import ExecutionContext


class PendingToolCall(Exception):
    """Raised internally when a remote agent requests a governed tool call."""

    def __init__(self, tool_name: str, payload: dict[str, Any]) -> None:
        super().__init__(f"pending remote tool call: {tool_name}")
        self.tool_name = tool_name
        self.payload = payload


class RemoteAgentExecutionContext:
    """Sandbox-side execution context that can request one governed tool call at a time."""

    def __init__(
        self,
        *,
        base_context: ExecutionContext,
        allowed_tools: list[str],
        max_tool_calls: int,
        tool_calls_used: int,
        resume_tool_name: str | None,
        resume_tool_result: dict[str, Any] | None,
    ) -> None:
        self.run_id = base_context.run_id
        self.workflow_name = base_context.workflow_name
        self.step_name = base_context.step_name
        self.approval_request = base_context.approval_request
        self._base_context = base_context
        self._allowed_tools = set(allowed_tools)
        self._max_tool_calls = max_tool_calls
        self._tool_calls = tool_calls_used
        self._resume_tool_name = resume_tool_name
        self._resume_tool_result = resume_tool_result

    def get_artifact(self, key: str, default: Any = None) -> Any:
        return self._base_context.get_artifact(key, default)

    def artifacts_snapshot(self) -> dict[str, Any]:
        return self._base_context.artifacts_snapshot()

    def set_metadata(self, key: str, value: Any) -> None:
        self._base_context.set_metadata(key, value)

    @property
    def tool_calls_used(self) -> int:
        return self._tool_calls

    async def use_tool(self, name: str, payload: Any) -> dict[str, Any]:
        if name not in self._allowed_tools:
            raise AgentToolNotAllowedError(f"Agent step {self.step_name} cannot call tool {name}")
        if self._resume_tool_name is not None:
            if self._resume_tool_name != name:
                raise AgentExecutionError(
                    f"Remote agent resumed with tool result for {self._resume_tool_name}, but requested {name}"
                )
            result = self._resume_tool_result or {}
            self._resume_tool_name = None
            self._resume_tool_result = None
            return result
        if self._tool_calls >= self._max_tool_calls:
            raise AgentLimitExceededError(
                f"Agent step {self.step_name} exceeded max_tool_calls={self._max_tool_calls}"
            )
        self._tool_calls += 1
        normalized = payload if isinstance(payload, dict) else {"value": payload}
        raise PendingToolCall(name, normalized)


def _error(code: str, message: str, **details: Any) -> RemoteExecutionFailure:
    return RemoteExecutionFailure(code=code, message=message, details=details)


async def _execute_inline_cli(request: RemoteToolExecutionRequest) -> dict[str, Any]:
    payload = json.dumps(request.input_payload).encode("utf-8")
    process = await asyncio.create_subprocess_exec(
        *(request.command or []),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(input=payload), timeout=request.timeout_seconds)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise RuntimeError("cli tool timed out") from exc

    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    if process.returncode != 0:
        raise RuntimeError(f"cli tool failed with exit_code={process.returncode}: {stderr_text or stdout_text}")
    try:
        parsed = json.loads(stdout_text or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"cli tool returned invalid JSON: {stdout_text[:200]}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("cli tool must return a JSON object")
    return parsed


def create_sandbox_app(
    *,
    tool_registry: Any,
    agent_registry: Any,
    bearer_token: str,
):
    """Create the FastAPI sandbox app. Requires governai[sandbox]."""
    try:
        from fastapi import FastAPI, Header, HTTPException
    except Exception as exc:  # pragma: no cover - optional dependency boundary
        raise RuntimeError("FastAPI is required to use the sandbox service; install governai[sandbox]") from exc

    if not bearer_token:
        raise ValueError("bearer_token must not be empty")

    app = FastAPI(title="GovernAI Sandbox", version="0.2.0")

    def require_auth(authorization: str | None) -> None:
        expected = f"Bearer {bearer_token}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/health")
    async def health(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        require_auth(authorization)
        return {"status": "ok"}

    @app.post("/execute/tool")
    async def execute_tool(
        request: RemoteToolExecutionRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(authorization)
        try:
            if request.tool_kind == "cli":
                if not request.command:
                    raise RuntimeError("remote CLI execution requires command")
                output_payload = await _execute_inline_cli(request)
            else:
                tool = tool_registry.get_remote(request.executor_name)
                context = ExecutionContext(
                    run_id=request.run_id,
                    workflow_name=request.workflow_name,
                    step_name=request.step_name,
                    artifacts=request.artifacts,
                    channels=request.channels,
                    metadata=request.metadata,
                )
                output = await tool.execute(context, request.input_payload)
                output_payload = output.model_dump(mode="json") if hasattr(output, "model_dump") else output
                if not isinstance(output_payload, dict):
                    output_payload = {"value": output_payload}
            return RemoteToolExecutionResponse(output_payload=output_payload).model_dump(mode="json")
        except KeyError:
            response = RemoteToolExecutionResponse(
                error=_error("not_found", f"Unknown remote tool: {request.executor_name}")
            )
        except ValidationError as exc:
            response = RemoteToolExecutionResponse(
                error=_error("validation_error", "Remote tool validation failed", errors=exc.errors())
            )
        except Exception as exc:
            response = RemoteToolExecutionResponse(error=_error("execution_failed", str(exc)))
        return response.model_dump(mode="json")

    @app.post("/execute/agent")
    async def execute_agent(
        request: RemoteAgentExecutionRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(authorization)
        try:
            agent = agent_registry.get_remote(request.executor_name)
            validated_input = agent.input_model.model_validate(request.input_payload)
            base_context = ExecutionContext(
                run_id=request.run_id,
                workflow_name=request.workflow_name,
                step_name=request.step_name,
                artifacts=request.artifacts,
                channels=request.channels,
                metadata=dict(request.metadata),
            )
            ctx = RemoteAgentExecutionContext(
                base_context=base_context,
                allowed_tools=request.allowed_tools,
                max_tool_calls=request.max_tool_calls,
                tool_calls_used=request.tool_calls_used,
                resume_tool_name=request.resume_tool_name,
                resume_tool_result=request.resume_tool_result,
            )
            task = AgentTask(
                task_id=str(uuid.uuid4()),
                goal=request.instruction,
                input_payload=validated_input.model_dump(mode="json"),
                context_artifacts=ctx.artifacts_snapshot(),
            )
            result_raw = agent.handler(ctx, task)
            if inspect.isawaitable(result_raw):
                result_raw = await result_raw
            result = AgentResult.model_validate(result_raw)
            if result.status == "final":
                validated_output = agent.output_model.model_validate(result.output_payload)
                response = RemoteAgentExecutionResponse(
                    status="final",
                    output_payload=validated_output.model_dump(mode="json"),
                )
            elif result.status == "handoff":
                if result.next_agent not in request.allowed_handoffs:
                    raise AgentExecutionError(
                        f"Remote agent {agent.name} attempted disallowed handoff to {result.next_agent}"
                    )
                response = RemoteAgentExecutionResponse(status="handoff", next_agent=result.next_agent)
            elif result.status == "needs_approval":
                response = RemoteAgentExecutionResponse(status="needs_approval", reason=result.reason)
            else:
                response = RemoteAgentExecutionResponse(
                    status="failed",
                    reason=result.reason,
                    error=_error("agent_failed", result.reason or f"Agent {agent.name} failed"),
                )
        except PendingToolCall as exc:
            response = RemoteAgentExecutionResponse(
                status="tool_call",
                requested_tool_call=RemoteToolCallRequest(tool_name=exc.tool_name, payload=exc.payload),
            )
        except KeyError:
            response = RemoteAgentExecutionResponse(
                status="failed",
                reason=f"Unknown remote agent: {request.executor_name}",
                error=_error("not_found", f"Unknown remote agent: {request.executor_name}"),
            )
        except ValidationError as exc:
            response = RemoteAgentExecutionResponse(
                status="failed",
                reason="Remote agent validation failed",
                error=_error("validation_error", "Remote agent validation failed", errors=exc.errors()),
            )
        except Exception as exc:
            response = RemoteAgentExecutionResponse(
                status="failed",
                reason=str(exc),
                error=_error("execution_failed", str(exc)),
            )
        return response.model_dump(mode="json")

    return app
