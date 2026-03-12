# governai

`governai` is a developer-facing Python framework for building governed AI backends with deterministic execution.

It is designed for teams that need explicit control over what runs next, what is allowed, what needs approval, and what happened during execution.

## What It Solves

- Typed tool contracts (Python and CLI tools) with strict input/output validation.
- Deterministic workflow chaining with strict, rule-based, or bounded transitions.
- Runtime-enforced control flow (not prompt-enforced).
- Policy checks before execution.
- Approval interruptions before risky actions.
- Full audit event streams for run lifecycle, transitions, policies, approvals, tools, and agents.
- Governed multi-agent workflows where agents are bounded executors inside the same runtime kernel.

## What It Intentionally Does Not Do (MVP)

- SaaS control plane
- visual builder UI
- distributed orchestration
- Temporal integration
- managed control-plane persistence
- auth/RBAC
- background scheduling
- autonomous free-form swarms

## Quickstart

Install as a library:

```bash
pip install governai
```

Install directly from git:

```bash
pip install "governai @ git+https://<your-git-host>/<org>/<repo>.git@main"
```

Local editable install for development:

```bash
pip install -e .[dev]
```

```python
from pydantic import BaseModel
from governai import Workflow, step, tool

class In(BaseModel):
    value: int

class Mid(BaseModel):
    value: int

class Out(BaseModel):
    value: int

@tool(name="add_one", input_model=In, output_model=Mid)
async def add_one(ctx, data: In) -> Mid:
    return Mid(value=data.value + 1)

@tool(name="double", input_model=Mid, output_model=Out)
async def double(ctx, data: Mid) -> Out:
    return Out(value=data.value * 2)

class MyFlow(Workflow[In, Out]):
    first = step("first", tool=add_one).then("second")
    second = step("second", tool=double).then_end()

# await MyFlow().run(In(value=2))
```

## Core Concepts

- **Tools**: typed executable units (`@tool` or `Tool.from_cli(...)`).
- **Skills**: named tool bundles.
- **Workflows**: explicit step graph with runtime-enforced transitions.
- **Policies**: allow/deny checks before execution.
- **Approvals**: interruption/resume gates for risky actions.
- **Audit events**: structured, in-memory event stream for inspection and tests.
- **Agents**: bounded role executors with allowlisted tools/handoffs, executed as workflow steps.

## Tools vs LLM Tool Calling

`Tool` in `governai` means "typed executable unit", not "LLM-only function".

- A tool can run as a normal deterministic workflow step (`step(..., tool=...)`).
- A tool can also be exposed to an LLM/agent (for example through `AgentExecutionContext.use_tool(...)`).
- LLM usage is optional. Governance (validation, policies, approvals, audit) still applies either way.

This separation is intentional:
- tools define *what can execute*
- transitions define *what can run next*
- agent/LLM logic only decides content or proposals inside those runtime bounds

## Deterministic Tool Chaining

In `governai`, chaining is encoded in workflow transitions (`then`, `branch`, `route_to`) and enforced by the runtime.

Control flow is **not** decided by prompts. The model/tool logic decides content; runtime decides next step; policy decides permission; approval decides whether risky actions can proceed.

## Governed App Layer

You can define flows declaratively using `GovernedFlowSpec` and compile them with `governed_flow(...)`.

```python
from governai import GovernedFlowSpec, GovernedStepSpec, governed_flow, then, end

spec = GovernedFlowSpec(
    name="minimal",
    steps=[
        GovernedStepSpec(name="first", tool=add_one, transition=then("second")),
        GovernedStepSpec(name="second", tool=double, transition=end()),
    ],
)

flow = governed_flow(spec)
# await flow.run(In(value=2))
```

Core additions in this layer:
- transport-agnostic execution backends (`AsyncBackend`, `ThreadPoolBackend`, `ProcessPoolBackend`)
- persistence abstractions (`RunStore`, `InMemoryRunStore`, `RedisRunStore`)
- interrupt contracts and manager (`InterruptManager`)
- generic integration helpers (`GovernedHTTPClient`, provider error normalization)

## Config And DSL Frontends

`governai` now supports additive frontends for workflow authoring:

- **Config compiler**: define `FlowConfigV1` in YAML/JSON and compile with `governed_flow_from_config(...)`.
- **Agent-specific DSL**: write text DSL, parse/compile with `parse_dsl(...)`, `dsl_to_flow_config(...)`, or `governed_flow_from_dsl(...)`.

Both frontends compile into the same governed runtime model and preserve deterministic transitions and policy/approval enforcement.

```python
from governai import AgentRegistry, ToolRegistry, governed_flow_from_config

tools = ToolRegistry()  # register tools before compile
flow = governed_flow_from_config(
    "examples/config/support_flow.yaml",
    tool_registry=tools,
    agent_registry=AgentRegistry(),
)
```

```python
from governai import AgentRegistry, ToolRegistry, governed_flow_from_dsl

dsl_text = '''
flow demo {
  step first: tool support.validate -> end;
}
'''
tools = ToolRegistry()  # register tools before compile
flow = governed_flow_from_dsl(
    dsl_text,
    tool_registry=tools,
    agent_registry=AgentRegistry(),
)
```


## Documentation

- Quickstart: [`docs/quickstart.md`](/Users/dondoe/coding/governai/docs/quickstart.md)
- Patterns: [`docs/patterns.md`](/Users/dondoe/coding/governai/docs/patterns.md)
- API Reference: [`docs/reference.md`](/Users/dondoe/coding/governai/docs/reference.md)
- Index: [`docs/USAGE.md`](/Users/dondoe/coding/governai/docs/USAGE.md)

## Example App

Run:

```bash
python examples/support_flow.py
```

Config/DSL equivalent run:

```bash
python examples/support_flow_from_definitions.py
```

This demonstrates:
- validate input
- fetch customer
- draft response via CLI tool
- approval interruption before send
- resume after approval
- audit trail output
