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
- runtime stores: `RunStore`, `InMemoryRunStore`, `RedisRunStore`
- interrupt runtime: `InterruptManager`, `InterruptRequest`, `InterruptResolution`
- integration helpers: `GovernedHTTPClient`, `ProviderErrorCode`, `parse_provider_error`
- `PolicyEngine`, `policy`, `PolicyDecision`, `PolicyContext`
- `ApprovalEngine`, `ApprovalDecision`, `ApprovalDecisionType`, `ApprovalRequest`
- `Agent`, `AgentRegistry`, `AgentTask`, `AgentResult`
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
- `await resume(run_id, decision)`
- `get_run_state(run_id)`

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

## Workflow Runtime

`await workflow.run(input)`:
- creates `RunState`
- executes from entry step
- enforces deterministic transitions
- stores artifacts
- emits audit events

`await workflow.resume(run_id, decision)`:
- applies approval decision
- resumes blocked run
- on reject => failed run + `ApprovalRejectedError`

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

## Audit Events

Emitter default: `InMemoryAuditEmitter`.

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
- `PolicyDeniedError`, `ApprovalRequiredError`, `ApprovalRejectedError`

Agent exceptions:
- `AgentExecutionError`, `AgentToolNotAllowedError`, `AgentLimitExceededError`

## Source Pointers

- core runtime: [`governai/runtime/local.py`](../governai/runtime/local.py)
- workflow model: [`governai/workflows/base.py`](../governai/workflows/base.py)
- tools: [`governai/tools/base.py`](../governai/tools/base.py)
- agents: [`governai/agents/base.py`](../governai/agents/base.py)
