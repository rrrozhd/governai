# governai

[![PyPI version](https://img.shields.io/pypi/v/governai)](https://pypi.org/project/governai/)
[![Python](https://img.shields.io/pypi/pyversions/governai)](https://pypi.org/project/governai/)
[![CI](https://img.shields.io/github/actions/workflow/status/rrrozhd/governai/ci.yml?branch=main&label=ci)](https://github.com/rrrozhd/governai/actions/workflows/ci.yml)

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

## Install

Requires Python 3.12+.

Install from PyPI:

```bash
pip install governai
```

Install with sandbox worker dependencies:

```bash
pip install "governai[sandbox]"
```

Install with Redis-backed run and interrupt persistence:

```bash
pip install "governai[redis]"
```

Install directly from GitHub:

```bash
pip install "governai @ git+https://github.com/rrrozhd/governai.git@main"
```

Local editable install for development:

```bash
pip install -e .[dev]
```

Local editable install with sandbox service support:

```bash
pip install -e .[dev,sandbox]
```

Local editable install with Redis support:

```bash
pip install -e .[dev,redis]
```

## Quickstart

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

Thread-native execution is additive. If you omit `thread_id`, behavior stays exactly the same as before and the run uses its generated `run_id` as the thread identity.

```python
state = await MyFlow().run(In(value=2), thread_id="thread-123")
latest = await MyFlow().get_latest_run_state("thread-123")
history = await MyFlow().list_thread_runs("thread-123")
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
- interrupt contracts and manager (`InterruptManager`, `InterruptStore`, `InMemoryInterruptStore`, `RedisInterruptStore`)
- generic integration helpers (`GovernedHTTPClient`, provider error normalization)

## Thread-Native Runs And Durable Interrupts

GovernAI now supports caller-supplied thread identity and thread-aware resume helpers without breaking existing `run_id` flows.

- `await flow.run(data, thread_id="thread-123")`
- `await flow.get_latest_run_state("thread-123")`
- `await flow.resume_latest("thread-123", payload)`
- `await flow.list_thread_runs("thread-123")`

Built-in stores now also support:

- active/latest run lookup by thread in `InMemoryRunStore` and `RedisRunStore`
- durable interrupt persistence in `InMemoryInterruptStore` and `RedisInterruptStore`
- audit events that carry `thread_id` as a top-level field

Minimal threaded resume example:

```python
from governai import ApprovalDecision, ApprovalDecisionType

state = await flow.run(payload, thread_id="thread-123")
latest = await flow.get_latest_run_state("thread-123")

if latest.pending_approval:
    latest = await flow.resume_latest(
        "thread-123",
        ApprovalDecision(
            decision=ApprovalDecisionType.APPROVE,
            decided_by="alice",
        ),
    )
```

Reference material:

- Threading and interrupts guide: [`docs/threading.md`](docs/threading.md)
- Minimal example: [`examples/thread_resume.py`](examples/thread_resume.py)

## Contained Execution

GovernAI now supports two runtime containment modes:

- `local_dev`: default. Tools and agents execute on the host machine.
- `strict_remote`: control plane stays local, but governed execution must go through a remote sandbox.

Placement is configured per tool or agent:

- `execution_placement="local_only"`: may only run on the host
- `execution_placement="remote_only"`: must run through the remote adapter
- `execution_placement="local_or_remote"`: local in `local_dev`, remote in `strict_remote`

In `strict_remote`:

- `local_only` executors are rejected at workflow construction time
- nested agent tool calls stay governed by the local runtime
- policies, approvals, audit, transitions, and run state remain local
- CLI containment only exists when the CLI tool is routed through the sandbox

Minimal control-plane setup:

```python
from governai import HTTPSandboxExecutionAdapter

flow = MyFlow(
    containment_mode="strict_remote",
    remote_execution_adapter=HTTPSandboxExecutionAdapter(
        base_url="https://sandbox.internal",
        bearer_token="replace-me",
    ),
)
```

Worker-side setup:

```python
from governai import AgentRegistry, ToolRegistry, create_sandbox_app

app = create_sandbox_app(
    tool_registry=ToolRegistry(),
    agent_registry=AgentRegistry(),
    bearer_token="replace-me",
)
```

Reference material:

- Containment guide: [`docs/sandbox.md`](docs/sandbox.md)
- End-to-end example: [`examples/strict_remote_sandbox.py`](examples/strict_remote_sandbox.py)

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

- Documentation index: [`docs/USAGE.md`](docs/USAGE.md)
- Changelog: [`CHANGELOG.md`](CHANGELOG.md)
- Threading and interrupts guide: [`docs/threading.md`](docs/threading.md)
- Quickstart: [`docs/quickstart.md`](docs/quickstart.md)
- Patterns: [`docs/patterns.md`](docs/patterns.md)
- Contained execution: [`docs/sandbox.md`](docs/sandbox.md)
- API Reference: [`docs/reference.md`](docs/reference.md)
- GitHub repository: [github.com/rrrozhd/governai](https://github.com/rrrozhd/governai)
- PyPI package: [pypi.org/project/governai](https://pypi.org/project/governai/)

## Example App

Run:

```bash
python examples/support_flow.py
```

Config/DSL equivalent run:

```bash
python examples/support_flow_from_definitions.py
```

Strict remote sandbox example:

```bash
python examples/strict_remote_sandbox.py
```

This demonstrates:
- validate input
- fetch customer
- draft response via CLI tool
- approval interruption before send
- resume after approval
- audit trail output
