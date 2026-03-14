# GovernAI API Reference (MVP)

This is a practical reference for key classes, decorators, and runtime behavior.

## Top-level Exports

Import from:

```python
from governai import ...
```

Primary exports:
- `Tool`, `tool`, `ToolRegistry`
- `Skill`, `SkillRegistry`
- `Workflow`, `step`
- `GovernedFlowSpec`, `GovernedStepSpec`, `governed_flow`
- config compiler: `FlowConfigV1`, `load_flow_config`, `flow_config_to_spec`, `governed_flow_from_config`
- DSL compiler: `DSLAst`, `parse_dsl`, `dsl_to_flow_config`, `governed_flow_from_dsl`
- transition helpers: `then`, `end`, `branch`, `route_to`
- execution backends: `ExecutionBackend`, `AsyncBackend`, `ThreadPoolBackend`, `ProcessPoolBackend`
- runtime stores: `RunStore`, `ThreadAwareRunStore`, `InMemoryRunStore`, `RedisRunStore`
- interrupt runtime: `InterruptManager`, `InterruptStore`, `InMemoryInterruptStore`, `RedisInterruptStore`, `InterruptRequest`, `InterruptResolution`
- integration helpers: `GovernedHTTPClient`, `ProviderErrorCode`, `parse_provider_error`
- remote execution: `HTTPSandboxExecutionAdapter`, `create_sandbox_app`
- `PolicyEngine`, `policy`, `PolicyDecision`, `PolicyContext`
- `ApprovalEngine`, `ApprovalDecision`, `ApprovalDecisionType`, `ApprovalRequest`
- `Agent`, `AgentRegistry`, `AgentTask`, `AgentResult`
- remote request/response models: `RemoteToolExecutionRequest`, `RemoteToolExecutionResponse`, `RemoteAgentExecutionRequest`, `RemoteAgentExecutionResponse`
- `InMemoryAuditEmitter`, `AuditEvent`
- enums/constants: `RunStatus`, `EventType`, `DeterminismMode`, `END_STEP`
- structured exceptions for tools/workflows/agents/approvals/policies

## Decorators

### `@tool(...)`
Defines a typed Python tool.

Key args:
- `name: str`
- `input_model: type[BaseModel]`
- `output_model: type[BaseModel]`
- `capabilities: list[str]`
- `side_effect: bool`
- `timeout_seconds: float | None`
- `requires_approval: bool`
- `tags: list[str] | None`
- `execution_placement: "local_only" | "remote_only" | "local_or_remote"`
- `remote_name: str | None`

### `step(...)`
Defines workflow step with exactly one executor.

Key args:
- `name: str`
- exactly one of `tool=` or `agent=`
- `required_artifacts: list[str] | None`
- `emitted_artifact: str | None`
- `approval_override: bool | None`

Transition methods:
- `.then(next_step)`
- `.then_end()`
- `.branch(router, mapping)`
- `.route_to(allowed=[...])`

### `@policy(name)`
Annotates policy functions for policy engine registration.

## Governed App Spec

`governed_flow(spec, ...)` compiles a `GovernedFlowSpec` into an executable governed flow.

Spec building blocks:
- `GovernedStepSpec`: step-level executor/transition declaration
- `TransitionSpec`: transition object created by `then(...)`, `end()`, `branch(...)`, `route_to(...)`
- `InterruptContract`: default interrupt TTL/pending limits for spec-level runtime defaults

`GovernedFlow` methods:
- `await run(data)`
- `await run(data, thread_id="thread-123")`
- `await resume(run_id, decision)`
- `await get_latest_run_state(thread_id)`
- `await resume_latest(thread_id, payload)`
- `await list_thread_runs(thread_id)`
- `await list_pending_interrupts(run_id)`
- `await get_pending_interrupt(run_id, interrupt_id)`
- `await get_latest_pending_interrupt(run_id)`
- `await list_thread_pending_interrupts(thread_id)`
- `get_run_state(run_id)`

Containment/runtime args:
- `containment_mode="local_dev" | "strict_remote"`
- `remote_execution_adapter=...`
- `interrupt_store=...`

## Config Compiler (`FlowConfigV1`)

Use a serializable config model (YAML/JSON) and compile it into a governed flow.

```python
from governai import AgentRegistry, ToolRegistry, governed_flow_from_config

tool_registry = ToolRegistry()
agent_registry = AgentRegistry()

flow = governed_flow_from_config(
    "path/to/flow.yaml",
    tool_registry=tool_registry,
    agent_registry=agent_registry,
)
```

Core APIs:
- `load_flow_config(path_or_obj, format="yaml|json|auto") -> FlowConfigV1`
- `flow_config_to_spec(config, ...) -> GovernedFlowSpec`
- `governed_flow_from_config(config_or_path, ...) -> GovernedFlow`

Config compile-time errors:
- unknown tool/agent/policy/skill references
- duplicate step names
- unknown entry step
- invalid transition targets

## DSL Compiler

The DSL is a thin frontend that compiles into `FlowConfigV1`.

```python
from governai import dsl_to_flow_config, governed_flow_from_dsl

config = dsl_to_flow_config(dsl_text)
flow = governed_flow_from_dsl(
    dsl_text,
    tool_registry=tool_registry,
    agent_registry=agent_registry,
)
```

Core APIs:
- `parse_dsl(text) -> DSLAst`
- `dsl_to_flow_config(text) -> FlowConfigV1`
- `governed_flow_from_dsl(text, ...) -> GovernedFlow`

Diagnostics:
- syntax errors include line/column
- semantic errors include line/column where available

## Tools

### Python tools
Execution pipeline:
1. validate input model
2. invoke handler (sync or async)
3. validate output model

Tool invocation modes:
- **Workflow-driven**: a workflow step executes a tool deterministically (`then`, `branch`, `route_to` decide control flow).
- **Agent/LLM-driven**: an agent may call allowlisted tools (`AgentExecutionContext.use_tool(...)`) inside governance limits.
- **Direct integration**: you can invoke tools from your own adapters/loops while preserving model validation.

Important: defining a `Tool` does not mean an LLM automatically gets to call it. Exposure is explicit.

### CLI tools (`Tool.from_cli`)
Supported modes in MVP:
- `input_mode="json-stdin"`
- `output_mode="json-stdout"`

Runtime handling:
- non-zero exit -> `CLIToolProcessError`
- invalid JSON output -> `CLIToolOutputError`
- timeout -> `CLIToolTimeoutError`

CLI containment note:
- `local_only` CLI tools still spawn host subprocesses
- remote containment only applies when the CLI tool is routed through the sandbox

## Workflow Runtime

`await workflow.run(input, *, thread_id=None)`:
- creates `RunState`
- executes from entry step
- enforces deterministic transitions
- stores artifacts
- emits audit events

Thread behavior:
- if `thread_id is None`, `RunState.thread_id` defaults to the generated `run_id`
- if `thread_id` is provided, it is persisted on the run and attached to emitted audit events
- built-in stores can resolve active/latest runs per thread without an external thread map

`await workflow.resume(run_id, decision)`:
- applies approval decision
- resumes blocked run
- on reject => failed run + `ApprovalRejectedError`

Thread helpers:
- `await workflow.get_latest_run_state(thread_id)` prefers the active run for the thread, then falls back to the latest persisted run
- `await workflow.resume_latest(thread_id, payload)` resolves the same target and resumes it
- `await workflow.list_thread_runs(thread_id)` returns oldest-to-newest history for the thread
- `await workflow.list_thread_pending_interrupts(thread_id)` aggregates pending interrupts across that thread

### Containment modes

- `local_dev`: existing host-executed behavior
- `strict_remote`: remote-only execution for `remote_only` and `local_or_remote` executors

In `strict_remote`, workflow construction fails if:
- a step executor is `local_only`
- an agent allowlists a `local_only` tool
- remote-capable executors exist without a configured adapter

### Remote execution contract

Control-plane adapter:
- `HTTPSandboxExecutionAdapter`

Worker factory:
- `create_sandbox_app(tool_registry=..., agent_registry=..., bearer_token=...)`

Remote models:
- `RemoteToolExecutionRequest`
- `RemoteToolExecutionResponse`
- `RemoteAgentExecutionRequest`
- `RemoteAgentExecutionResponse`

Worker registry resolution:
- Python tools/agents resolve by `remote_name`
- CLI commands are sent inline in the request

Nested remote agent tool calls remain governed by the local runtime.

### Run statuses
- `PENDING`
- `RUNNING`
- `WAITING_APPROVAL`
- `COMPLETED`
- `FAILED`

## Policies

Policy function input: `PolicyContext`
- `workflow_name`
- `step_name`
- `tool_name`
- `capabilities`
- `side_effect`
- `artifacts`
- `pending_approval`
- `metadata`

Policy function output: `PolicyDecision`
- `allow: bool`
- `reason: str | None`
- `requires_approval: bool`

## Approvals

Approval is required when:
- executor has `requires_approval=True`, or
- step has `approval_override=True`

When blocked:
- state -> `WAITING_APPROVAL`
- `pending_approval` populated
- `approval_requested` event emitted

Interrupt durability:
- default interrupt persistence is in-memory
- `InMemoryInterruptStore` preserves current behavior
- `RedisInterruptStore` makes interrupts and per-run epochs restart-safe
- runtime methods expose pending interrupt inspection without changing `resume(run_id, ...)`

## Audit Events

Emitter default: `InMemoryAuditEmitter`.

`AuditEvent` includes:
- `thread_id: str | None`

Important event categories:
- run: start/complete/fail
- step entered + transition chosen
- policy checked/denied
- approval requested/granted/rejected
- tool start/completed/failed
- agent entered/completed/failed
- agent handoff proposed/accepted/rejected
- agent nested tool call start/completed/failed

## Agents

`Agent` fields include:
- identity: `name`, `description`, `instruction`
- contracts: `input_model`, `output_model`
- governance: `allowed_tools`, `allowed_handoffs`
- limits: `max_turns`, `max_tool_calls`
- execution metadata: `capabilities`, `side_effect`, `requires_approval`, `tags`
- placement metadata: `execution_placement`, `remote_name`

Agent handler signature:

```python
async def handler(ctx, task) -> AgentResult | dict:
    ...
```

`AgentResult.status` values:
- `final`
- `handoff`
- `needs_approval`
- `failed`

`AgentExecutionContext.use_tool(...)` enforces:
- allowlisted tool usage
- max tool-call budget
- policy + approval checks on nested calls
- nested audit events

## Exceptions (Main)

Tool exceptions:
- `ToolValidationError`, `ToolExecutionError`
- `CLIToolProcessError`, `CLIToolOutputError`, `CLIToolTimeoutError`

Workflow exceptions:
- `WorkflowDefinitionError`, `StepNotFoundError`
- `IllegalTransitionError`, `BranchResolutionError`, `RoutingResolutionError`
- `PolicyDeniedError`, `ApprovalRequiredError`, `ApprovalRejectedError`, `ContainmentPolicyError`

Agent exceptions:
- `AgentExecutionError`, `AgentToolNotAllowedError`, `AgentLimitExceededError`

## Source Pointers

- core runtime: [`governai/runtime/local.py`](../governai/runtime/local.py)
- workflow model: [`governai/workflows/base.py`](../governai/workflows/base.py)
- run stores: [`governai/runtime/run_store.py`](../governai/runtime/run_store.py)
- interrupts: [`governai/runtime/interrupts.py`](../governai/runtime/interrupts.py)
- tools: [`governai/tools/base.py`](../governai/tools/base.py)
- agents: [`governai/agents/base.py`](../governai/agents/base.py)
