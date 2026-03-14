from __future__ import annotations

import asyncio
import inspect
import sys
from typing import Any
from urllib.parse import urlsplit

import pytest
from pydantic import BaseModel

from governai import (
    Agent,
    AgentExecutionError,
    AgentResult,
    ApprovalDecision,
    ApprovalDecisionType,
    ContainmentPolicyError,
    EventType,
    GovernedHTTPError,
    HTTPResponse,
    HTTPSandboxExecutionAdapter,
    PolicyDecision,
    PolicyDeniedError,
    RemoteAgentExecutionRequest,
    RemoteAgentExecutionResponse,
    RemoteToolCallRequest,
    RemoteToolExecutionRequest,
    RemoteToolExecutionResponse,
    RunStatus,
    Tool,
    ToolRegistry,
    Workflow,
    step,
    tool,
)
from governai.agents.registry import AgentRegistry
from governai.sandbox.service import create_sandbox_app


class NumberIn(BaseModel):
    value: int


class NumberOut(BaseModel):
    value: int


class ToolOut(BaseModel):
    result: int


class AgentOut(BaseModel):
    done: bool
    value: int | None = None


class RecordingAdapter:
    def __init__(
        self,
        *,
        tool_handler: Any = None,
        agent_handler: Any = None,
    ) -> None:
        self.tool_requests: list[RemoteToolExecutionRequest] = []
        self.agent_requests: list[RemoteAgentExecutionRequest] = []
        self._tool_handler = tool_handler
        self._agent_handler = agent_handler

    async def execute_tool(self, request: RemoteToolExecutionRequest) -> RemoteToolExecutionResponse:
        self.tool_requests.append(request)
        if self._tool_handler is None:
            return RemoteToolExecutionResponse(output_payload=request.input_payload)
        response = self._tool_handler(request)
        if inspect.isawaitable(response):
            response = await response
        return response

    async def execute_agent(self, request: RemoteAgentExecutionRequest) -> RemoteAgentExecutionResponse:
        self.agent_requests.append(request)
        if self._agent_handler is None:
            return RemoteAgentExecutionResponse(status="final", output_payload={"done": True})
        response = self._agent_handler(request)
        if inspect.isawaitable(response):
            response = await response
        return response

    async def health(self) -> dict[str, Any]:
        return {"status": "ok"}


def _build_http_adapter(app: Any, *, token: str = "sandbox-token") -> HTTPSandboxExecutionAdapter:
    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    client = fastapi_testclient.TestClient(app)
    adapter = HTTPSandboxExecutionAdapter(base_url="http://sandbox.test", bearer_token=token)

    async def fake_request(
        *,
        method: str,
        url: str,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        accept_status: set[int] | None = None,
    ) -> HTTPResponse:
        response = client.request(method, urlsplit(url).path, json=json_body, headers=headers or {})
        if accept_status and response.status_code not in accept_status:
            raise GovernedHTTPError(
                "HTTP status not accepted",
                status_code=response.status_code,
                body=response.text,
            )
        return HTTPResponse(
            status_code=response.status_code,
            headers={key.lower(): value for key, value in response.headers.items()},
            body=response.content,
        )

    adapter.http_client.request = fake_request  # type: ignore[method-assign]
    return adapter


@tool(name="remote.local_only", input_model=NumberIn, output_model=NumberOut)
async def local_only_tool(ctx, data: NumberIn) -> NumberOut:  # noqa: ARG001
    return NumberOut(value=data.value + 1)


def test_strict_remote_rejects_local_only_step_executor() -> None:
    class Flow(Workflow[NumberIn, NumberOut]):
        start = step("run", tool=local_only_tool).then_end()

    with pytest.raises(ContainmentPolicyError, match="local_only"):
        Flow(containment_mode="strict_remote", remote_execution_adapter=RecordingAdapter())


def test_strict_remote_rejects_agent_allowlisting_local_only_tool() -> None:
    async def should_not_run(ctx, task):  # noqa: ARG001
        return AgentResult(status="final", output_payload={"done": True})

    agent = Agent(
        name="remote.agent.with.local.tool",
        description="",
        instruction="",
        handler=should_not_run,
        input_model=NumberIn,
        output_model=AgentOut,
        allowed_tools=["remote.local_only"],
        allowed_handoffs=[],
        execution_placement="remote_only",
    )

    class Flow(Workflow[NumberIn, AgentOut]):
        start = step("run", agent=agent).then_end()

    registry = ToolRegistry()
    registry.register(local_only_tool)

    with pytest.raises(ContainmentPolicyError, match="allowlists local_only tool"):
        Flow(
            tool_registry=registry,
            containment_mode="strict_remote",
            remote_execution_adapter=RecordingAdapter(),
        )


def test_remote_capable_executor_requires_remote_adapter() -> None:
    @tool(
        name="remote.requires.adapter",
        input_model=NumberIn,
        output_model=NumberOut,
        execution_placement="remote_only",
    )
    async def remote_tool(ctx, data: NumberIn) -> NumberOut:  # noqa: ARG001
        return NumberOut(value=data.value)

    class Flow(Workflow[NumberIn, NumberOut]):
        start = step("run", tool=remote_tool).then_end()

    with pytest.raises(ContainmentPolicyError, match="remote_execution_adapter"):
        Flow()


def test_local_or_remote_stays_local_in_local_dev() -> None:
    calls = {"count": 0}

    @tool(
        name="remote.flex.local",
        input_model=NumberIn,
        output_model=NumberOut,
        execution_placement="local_or_remote",
    )
    async def flex_tool(ctx, data: NumberIn) -> NumberOut:  # noqa: ARG001
        calls["count"] += 1
        return NumberOut(value=data.value + 3)

    class Flow(Workflow[NumberIn, NumberOut]):
        start = step("run", tool=flex_tool).then_end()

    async def run() -> None:
        adapter = RecordingAdapter(
            tool_handler=lambda request: RemoteToolExecutionResponse(output_payload={"value": 999})
        )
        flow = Flow(containment_mode="local_dev", remote_execution_adapter=adapter)
        state = await flow.run(NumberIn(value=2))
        assert state.status == RunStatus.COMPLETED
        assert state.artifacts["run"]["value"] == 5
        assert calls["count"] == 1
        assert adapter.tool_requests == []

    asyncio.run(run())


def test_remote_only_cli_tool_uses_adapter_in_strict_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    cli_tool = Tool.from_cli(
        name="remote.cli",
        command=[sys.executable, "-c", "raise SystemExit(0)"],
        input_model=NumberIn,
        output_model=ToolOut,
        execution_placement="remote_only",
        remote_name="sandbox.remote.cli",
    )

    async def forbidden_subprocess(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        raise AssertionError("host subprocess execution must not occur in strict_remote")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden_subprocess)

    class Flow(Workflow[NumberIn, ToolOut]):
        start = step("run", tool=cli_tool).then_end()

    async def run() -> None:
        adapter = RecordingAdapter(
            tool_handler=lambda request: RemoteToolExecutionResponse(
                output_payload={"result": request.input_payload["value"] + 5}
            )
        )
        flow = Flow(containment_mode="strict_remote", remote_execution_adapter=adapter)
        state = await flow.run(NumberIn(value=2))
        assert state.status == RunStatus.COMPLETED
        assert state.artifacts["run"]["result"] == 7
        assert len(adapter.tool_requests) == 1
        assert adapter.tool_requests[0].tool_kind == "cli"
        assert adapter.tool_requests[0].command == cli_tool.command

    asyncio.run(run())


def test_remote_only_agent_uses_adapter_in_strict_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    async def should_not_run(ctx, task):  # noqa: ARG001
        raise AssertionError("local agent execution must not occur in strict_remote")

    agent = Agent(
        name="remote.agent.final",
        description="",
        instruction="finish",
        handler=should_not_run,
        input_model=NumberIn,
        output_model=AgentOut,
        allowed_tools=[],
        allowed_handoffs=[],
        execution_placement="remote_only",
        remote_name="sandbox.remote.agent.final",
    )

    async def forbidden_execute(ctx, data):  # noqa: ARG001
        raise AssertionError("agent.execute must not be called for remote execution")

    monkeypatch.setattr(agent, "execute", forbidden_execute)

    class Flow(Workflow[NumberIn, AgentOut]):
        start = step("run", agent=agent).then_end()

    async def run() -> None:
        adapter = RecordingAdapter(
            agent_handler=lambda request: RemoteAgentExecutionResponse(
                status="final",
                output_payload={"done": True, "value": request.input_payload["value"] + 1},
            )
        )
        flow = Flow(containment_mode="strict_remote", remote_execution_adapter=adapter)
        state = await flow.run(NumberIn(value=4))
        assert state.status == RunStatus.COMPLETED
        assert state.artifacts["run"]["done"] is True
        assert state.artifacts["run"]["value"] == 5
        assert len(adapter.agent_requests) == 1

    asyncio.run(run())


def test_remote_agent_nested_tool_calls_stay_governed(monkeypatch: pytest.MonkeyPatch) -> None:
    policy_calls: list[tuple[str, bool]] = []

    @tool(
        name="remote.math",
        input_model=NumberIn,
        output_model=NumberOut,
        execution_placement="remote_only",
        remote_name="sandbox.remote.math",
    )
    async def remote_tool(ctx, data: NumberIn) -> NumberOut:  # noqa: ARG001
        raise AssertionError("local tool execution must not occur in strict_remote")

    async def should_not_run(ctx, task):  # noqa: ARG001
        raise AssertionError("local agent handler must not run in strict_remote")

    agent = Agent(
        name="remote.agent.nested",
        description="",
        instruction="use the tool once",
        handler=should_not_run,
        input_model=NumberIn,
        output_model=AgentOut,
        allowed_tools=["remote.math"],
        allowed_handoffs=[],
        max_tool_calls=1,
        execution_placement="remote_only",
        remote_name="sandbox.remote.agent.nested",
    )

    async def forbidden_tool_execute(ctx, data):  # noqa: ARG001
        raise AssertionError("tool.execute must not be called for remote execution")

    async def forbidden_agent_execute(ctx, data):  # noqa: ARG001
        raise AssertionError("agent.execute must not be called for remote execution")

    monkeypatch.setattr(remote_tool, "execute", forbidden_tool_execute)
    monkeypatch.setattr(agent, "execute", forbidden_agent_execute)

    def allow_nested(ctx) -> PolicyDecision:
        policy_calls.append((ctx.tool_name, bool(ctx.metadata.get("nested"))))
        return PolicyDecision(allow=True)

    def handle_agent(request: RemoteAgentExecutionRequest) -> RemoteAgentExecutionResponse:
        if request.resume_tool_name is None:
            return RemoteAgentExecutionResponse(
                status="tool_call",
                requested_tool_call=RemoteToolCallRequest(
                    tool_name="remote.math",
                    payload={"value": request.input_payload["value"]},
                ),
            )
        assert request.resume_tool_name == "remote.math"
        assert request.resume_tool_result == {"value": request.input_payload["value"] * 10}
        return RemoteAgentExecutionResponse(
            status="final",
            output_payload={"done": True, "value": request.resume_tool_result["value"]},
        )

    def handle_tool(request: RemoteToolExecutionRequest) -> RemoteToolExecutionResponse:
        return RemoteToolExecutionResponse(output_payload={"value": request.input_payload["value"] * 10})

    class Flow(Workflow[NumberIn, AgentOut]):
        start = step("run", agent=agent).then_end()

    async def run() -> None:
        adapter = RecordingAdapter(tool_handler=handle_tool, agent_handler=handle_agent)
        registry = ToolRegistry()
        registry.register(remote_tool)
        flow = Flow(
            tool_registry=registry,
            containment_mode="strict_remote",
            remote_execution_adapter=adapter,
        )
        flow.runtime.policy_engine.register(allow_nested, workflow_name=flow.name)
        state = await flow.run(NumberIn(value=3))
        assert state.status == RunStatus.COMPLETED
        assert state.artifacts["run"]["done"] is True
        assert state.artifacts["run"]["value"] == 30
        assert len(adapter.agent_requests) == 2
        assert len(adapter.tool_requests) == 1
        assert ("remote.math", True) in policy_calls
        event_types = [event.event_type for event in flow.runtime.audit_emitter.events]
        assert EventType.AGENT_TOOL_CALL_STARTED in event_types
        assert EventType.AGENT_TOOL_CALL_COMPLETED in event_types
        assert EventType.POLICY_CHECKED in event_types

    asyncio.run(run())


def test_remote_tool_approval_pauses_locally_and_resumes() -> None:
    @tool(
        name="remote.approval",
        input_model=NumberIn,
        output_model=NumberOut,
        requires_approval=True,
        execution_placement="remote_only",
    )
    async def approval_tool(ctx, data: NumberIn) -> NumberOut:  # noqa: ARG001
        return NumberOut(value=data.value)

    class Flow(Workflow[NumberIn, NumberOut]):
        start = step("run", tool=approval_tool).then_end()

    async def run() -> None:
        adapter = RecordingAdapter(
            tool_handler=lambda request: RemoteToolExecutionResponse(
                output_payload={"value": request.input_payload["value"] + 2}
            )
        )
        flow = Flow(containment_mode="strict_remote", remote_execution_adapter=adapter)
        state = await flow.run(NumberIn(value=5))
        assert state.status == RunStatus.WAITING_APPROVAL
        assert adapter.tool_requests == []

        resumed = await flow.resume(
            state.run_id,
            ApprovalDecision(decision=ApprovalDecisionType.APPROVE, decided_by="tester"),
        )
        assert resumed.status == RunStatus.COMPLETED
        assert resumed.artifacts["run"]["value"] == 7
        assert len(adapter.tool_requests) == 1

    asyncio.run(run())


def test_policy_denial_happens_before_remote_execution() -> None:
    @tool(
        name="remote.policy.denied",
        input_model=NumberIn,
        output_model=NumberOut,
        execution_placement="remote_only",
    )
    async def denied_tool(ctx, data: NumberIn) -> NumberOut:  # noqa: ARG001
        return NumberOut(value=data.value)

    class Flow(Workflow[NumberIn, NumberOut]):
        start = step("run", tool=denied_tool).then_end()

    def deny_all(ctx) -> PolicyDecision:  # noqa: ARG001
        return PolicyDecision(allow=False, reason="blocked")

    async def run() -> None:
        adapter = RecordingAdapter()
        flow = Flow(containment_mode="strict_remote", remote_execution_adapter=adapter)
        flow.runtime.policy_engine.register(deny_all, workflow_name=flow.name)
        with pytest.raises(PolicyDeniedError, match="blocked"):
            await flow.run(NumberIn(value=1))
        assert adapter.tool_requests == []

    asyncio.run(run())


def test_remote_agent_handoff_validation_stays_local() -> None:
    async def should_not_run(ctx, task):  # noqa: ARG001
        raise AssertionError("local agent handler must not run in strict_remote")

    agent = Agent(
        name="remote.agent.handoff",
        description="",
        instruction="handoff",
        handler=should_not_run,
        input_model=NumberIn,
        output_model=AgentOut,
        allowed_tools=[],
        allowed_handoffs=["known.agent"],
        execution_placement="remote_only",
    )

    class Flow(Workflow[NumberIn, AgentOut]):
        start = step("run", agent=agent).then_end()

    async def run() -> None:
        adapter = RecordingAdapter(
            agent_handler=lambda request: RemoteAgentExecutionResponse(
                status="handoff",
                next_agent="known.agent",
            )
        )
        flow = Flow(containment_mode="strict_remote", remote_execution_adapter=adapter)
        with pytest.raises(AgentExecutionError, match="Unknown handoff target agent"):
            await flow.run(NumberIn(value=1))
        event_types = [event.event_type for event in flow.runtime.audit_emitter.events]
        assert EventType.AGENT_HANDOFF_PROPOSED in event_types
        assert EventType.AGENT_HANDOFF_REJECTED in event_types

    asyncio.run(run())


def test_http_sandbox_tool_execution_end_to_end() -> None:
    @tool(
        name="control.http.tool",
        input_model=NumberIn,
        output_model=NumberOut,
        execution_placement="remote_only",
        remote_name="sandbox.http.tool",
    )
    async def control_tool(ctx, data: NumberIn) -> NumberOut:  # noqa: ARG001
        raise AssertionError("control-plane tool must not execute locally")

    @tool(
        name="sandbox.http.tool.impl",
        input_model=NumberIn,
        output_model=NumberOut,
        remote_name="sandbox.http.tool",
    )
    async def sandbox_tool(ctx, data: NumberIn) -> NumberOut:  # noqa: ARG001
        return NumberOut(value=data.value * 4)

    class Flow(Workflow[NumberIn, NumberOut]):
        start = step("run", tool=control_tool).then_end()

    async def run() -> None:
        sandbox_tools = ToolRegistry()
        sandbox_tools.register(sandbox_tool)
        app = create_sandbox_app(
            tool_registry=sandbox_tools,
            agent_registry=AgentRegistry(),
            bearer_token="sandbox-token",
        )
        adapter = _build_http_adapter(app)
        flow = Flow(containment_mode="strict_remote", remote_execution_adapter=adapter)
        health = await adapter.health()
        assert health["status"] == "ok"
        state = await flow.run(NumberIn(value=3))
        assert state.status == RunStatus.COMPLETED
        assert state.artifacts["run"]["value"] == 12

    asyncio.run(run())


def test_http_sandbox_agent_execution_end_to_end() -> None:
    @tool(
        name="control.http.agent.tool",
        input_model=NumberIn,
        output_model=NumberOut,
        execution_placement="remote_only",
        remote_name="sandbox.http.agent.tool",
    )
    async def control_tool(ctx, data: NumberIn) -> NumberOut:  # noqa: ARG001
        raise AssertionError("control-plane tool must not execute locally")

    @tool(
        name="sandbox.http.agent.tool.impl",
        input_model=NumberIn,
        output_model=NumberOut,
        remote_name="sandbox.http.agent.tool",
    )
    async def sandbox_tool(ctx, data: NumberIn) -> NumberOut:  # noqa: ARG001
        return NumberOut(value=data.value + 9)

    async def control_agent_handler(ctx, task):  # noqa: ARG001
        raise AssertionError("control-plane agent must not execute locally")

    async def sandbox_agent_handler(ctx, task):
        tool_result = await ctx.use_tool("control.http.agent.tool", {"value": task.input_payload["value"]})
        return AgentResult(status="final", output_payload={"done": True, "value": tool_result["value"]})

    control_agent = Agent(
        name="control.http.agent",
        description="",
        instruction="call the tool",
        handler=control_agent_handler,
        input_model=NumberIn,
        output_model=AgentOut,
        allowed_tools=["control.http.agent.tool"],
        allowed_handoffs=[],
        max_tool_calls=1,
        execution_placement="remote_only",
        remote_name="sandbox.http.agent",
    )
    sandbox_agent = Agent(
        name="sandbox.http.agent.impl",
        description="",
        instruction="call the tool",
        handler=sandbox_agent_handler,
        input_model=NumberIn,
        output_model=AgentOut,
        allowed_tools=["control.http.agent.tool"],
        allowed_handoffs=[],
        max_tool_calls=1,
        remote_name="sandbox.http.agent",
    )

    class Flow(Workflow[NumberIn, AgentOut]):
        start = step("run", agent=control_agent).then_end()

    async def run() -> None:
        control_tools = ToolRegistry()
        control_tools.register(control_tool)

        sandbox_tools = ToolRegistry()
        sandbox_tools.register(sandbox_tool)
        sandbox_agents = AgentRegistry()
        sandbox_agents.register(sandbox_agent)

        app = create_sandbox_app(
            tool_registry=sandbox_tools,
            agent_registry=sandbox_agents,
            bearer_token="sandbox-token",
        )
        adapter = _build_http_adapter(app)
        flow = Flow(
            tool_registry=control_tools,
            containment_mode="strict_remote",
            remote_execution_adapter=adapter,
        )
        state = await flow.run(NumberIn(value=2))
        assert state.status == RunStatus.COMPLETED
        assert state.artifacts["run"]["done"] is True
        assert state.artifacts["run"]["value"] == 11

    asyncio.run(run())
